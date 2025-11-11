# Harman 코딩 과제 - Kubernetes 노드 모니터링 DaemonSet

본 문서는 Kubernetes 환경에서 노드 파일 시스템을 모니터링하는 에이전트를 개발하는 과제의 최종 결과물입니다.

## 1\. 과제 요구사항 분석

본 과제는 Kubernetes(K8s) 환경에서 다음과 같은 요구사항을 충족하는 모니터링 에이전트를 개발하는 것을 목표로 합니다.

*   **배포 방식:** K8s `DaemonSet`을(를) 사용하여 클러스터의 모든 노드에 에이전트를 배포해야 합니다.
*   **파일 접근:** 각 노드의 특정 호스트 디렉토리(예: `/mnt/harman`)를 `hostPath` 볼륨으로 마운트해야 합니다.
*   **핵심 로직:** `CronJob`이(가) 아닌, `while True` + `time.sleep`과(와) 같은 롱-러닝(long-running) 프로세스로 구현되어야 합니다.
*   **주기적 수집:** 설정 가능한 주기(예: 60초)마다 마운트된 디렉토리의 파일 목록을 스캔해야 합니다.
*   **데이터 저장:** 수집된 데이터를 K8s 클러스터 내부에 설치된 RDBMS(PostgreSQL)에 저장해야 합니다.
*   **DB 스키마:** `NodeName` (수집된 노드명), `MountPath` (경로), `FileList` (JSON 형태), `CollectedAt` (타임스탬프) 컬럼이 반드시 포함되어야 합니다.
*   **보안:** DB 인증 정보는 K8s `Secret`을(를) 통해 관리되어야 합니다.
*   **인프라:** DB는 `Helm`을(를) 사용해 배포해야 합니다.
*   **산출물:** `Dockerfile`, 소스 코드, K8s 매니페스트(`daemonset.yaml` 등), `README.md`, `tar` 압축 파일, `git` 커밋 이력을 제출해야 합니다.

---

## 2\. 단계별 수행 가이드

위 요구사항을 충족하기 위해 진행한 단계별 상세 가이드입니다.

### Step 1: 프로젝트 및 K8s 클러스터 환경 구성

**a. 프로젝트 초기화 (로컬)**
`git init`으로 리포지토리를 생성하고, `src/`, `k8s/`, `helm/` 디렉토리 구조를 생성했습니다. `Dockerfile`, `requirements.txt` 등 기본 파일도 함께 생성했습니다.

**b. Minikube 2-Node 클러스터 생성**
PDF 가이드라인에 따라 2개의 노드를 가진 Minikube 클러스터를 생성했습니다.
(참고: `root` 계정으로 실행 시 `docker` 드라이버는 `--force` 옵션이 필요했습니다.)

```shell
minikube start -p harman --nodes 2 \
--container-runtime=containerd --cni=cilium \
--cpus 2 --memory 2048MB --force
```

**c. `hostPath` 디렉토리 및 테스트 파일 생성**
`DaemonSet`이(가) 모니터링할 대상 디렉토리(`/mnt/harman`)와(와) 테스트용 파일을 *두 개의 노드 각각*에 `minikube ssh`로 접속하여 생성했습니다.

```shell
# 첫 번째 노드 (harman)
minikube ssh -p harman -n harman
sudo mkdir -p /mnt/harman
sudo touch /mnt/harman/control_plane_file.txt
sudo touch /mnt/harman/system.log
exit

# 두 번째 노드 (harman-m02)
minikube ssh -p harman -n harman-m02
sudo mkdir -p /mnt/harman
sudo touch /mnt/harman/worker_node_data.json
exit
```

### Step 2: PostgreSQL 데이터베이스 배포 (Helm)

**a. `helm/postgres-values.yaml` 작성**
Bitnami PostgreSQL 차트 배포를 위한 `values.yaml` 파일을 작성했습니다.

**핵심 수정 사항:** Minikube의 `hostPath` 기반 Persistent Volume과 Bitnami의 non-root 컨테이너 간의 권한 충돌(로그: `Permission denied`)을(를) 해결하기 위해, `volumePermissions.enabled: true` 설정을 추가했습니다.

```yaml
auth:
  username: "harman_user"
  password: "harman_pass"
  database: "harman_db"

volumePermissions:
  enabled: true
```

**b. Helm 배포**
`database` 네임스페이스를 생성하며 PostgreSQL을 배포했습니다.

```shell
helm repo add bitnami [https://charts.bitnami.com/bitnami](https://charts.bitnami.com/bitnami)
helm install harman-db bitnami/postgresql -f helm/postgres-values.yaml --namespace database --create-namespace
```

### Step 3: 애플리케이션 개발 (`src/main.py`) 및 이미지 빌드

**a. `src/main.py` 동작 상세**
에이전트는 `while True:` 루프와 `time.sleep()`을(를) 사용한 롱-러닝(long-running) 프로세스로 구현되었습니다.

1.  **설정 로드:** `os.environ.get()`을(를) 사용하여 K8s `DaemonSet` 및 `Secret`으로부터 주입된 환경 변수(예: `DB_HOST`, `MY_NODE_NAME`, `MOUNT_PATH`, `SCAN_INTERVAL` 등)를 읽어들입니다.
2.  **DB 초기화:** `ensure_table_exists()` 함수가 `CREATE TABLE IF NOT EXISTS file_monitor (...)` SQL을 실행합니다. (이때 `CollectedAt TIMESTAMPTZ NOT NULL`로 정확한 타임스탬프 타입을 지정했습니다.)
3.  **데이터 수집:** `scan_files()` 함수가 `os.listdir()`을(를) 사용해 `MOUNT_PATH`의 파일 목록을 스캔합니다.
4.  **데이터 저장:** `insert_data()` 함수가 `INSERT INTO...` SQL을 실행하여 `NODE_NAME`과(와) 파일 목록(JSON 형태), 현재 시각을 DB에 저장합니다.
5.  **로깅:** 모든 동작은 `print(..., flush=True)`를 통해 표준 출력(stdout)으로 로깅되어 `kubectl logs`로 확인할 수 있습니다.

**b. `Dockerfile` 작성**
Python 코드를 실행하기 위한 `Dockerfile`을(를) 작성했습니다.

**c. 이미지 빌드 및 Minikube 로드**
이미지를 빌드하고, `minikube image load`를(를) 통해 외부 레지스트리 없이 로컬 이미지를 Minikube 노드에 직접 로드했습니다.

```shell
docker build -t harman-agent:0.1.
minikube image load harman-agent:0.1 -p harman
```

### Step 4: DaemonSet 배포

**a. `k8s/secret.yaml` 작성 및 적용**
`main.py`가(이) DB에 접속하는 데 필요한 인증 정보를 `Secret`으로(로) 정의했습니다. `DB_HOST`에는 K8s 내부 DNS 주소(`harman-db-postgresql.database.svc.cluster.local`)를 명시했습니다.

```shell
kubectl apply -f k8s/secret.yaml
```

**b. `k8s/daemonset.yaml` 작성 및 적용**
모든 구성 요소를 통합하는 `DaemonSet` 매니페스트를 작성했습니다.

**핵심 수정 사항:** `envFrom`을(를) 통해 `Secret`을(를) 참조하기 위해, `DaemonSet`의 `namespace:`를 `Secret`이(가) 존재하는 `database`로(로) 지정하여 `unknown field "namespace"` 오류를 해결했습니다.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: harman-agent
  # Secret과(와) 동일한 네임스페이스에 배포
  namespace: database
spec:
  template:
    spec:
      containers:
      - name: harman-agent
        image: harman-agent:0.1
        imagePullPolicy: IfNotPresent
        env:
          # 1. 주기 설정 (환경 변수)
          - name: SCAN_INTERVAL
            value: "60"
          # 2. 컨테이너 내부 마운트 경로
          - name: MOUNT_PATH 
            value: "/mnt/node-data"
          # 3. Downward API로 노드 이름 주입
          - name: MY_NODE_NAME
            valueFrom:
              fieldRef:
                fieldPath: spec.nodeName
        # 4. Secret 참조
        envFrom:
        - secretRef:
            name: db-credentials
        # 5. hostPath 볼륨 마운트
        volumeMounts:
        - name: host-data-dir
          mountPath: /mnt/node-data
          readOnly: true
      volumes:
      - name: host-data-dir
        hostPath:
          path: /mnt/harman
          type: Directory
```

```shell
kubectl apply -f k8s/daemonset.yaml
```

---

## 3\. 최종 검증 방법

모든 배포가 완료된 후(약 1-2분 소요), 다음 명령어로 정상 동작을 검증했습니다.

### a. 파드 상태 확인

`DaemonSet`이(가) 2개의 노드에 각각 파드를 생성했는지, 그리고 모두 `Running` 상태인지 확인합니다.

```shell
kubectl get pods -n database -l app=harman-agent -o wide
```

### b. 실시간 로그 확인

`harman` 및 `harman-m02` 노드 양쪽에서 `Successfully saved data...` 메시지가 주기적으로 출력되는지 확인합니다.

```shell
kubectl logs -f -n database -l app=harman-agent
```

### c. DB 데이터 최종 확인 (성공)

`kubectl exec`로 PostgreSQL 파드에 직접 접속하여 `file_monitor` 테이블의 데이터를 조회했습니다. (암호: `harman_pass`)

```shell
kubectl exec -it -n database harman-db-postgresql-0 -- psql -U harman_user -d harman_db -c "SELECT * FROM file_monitor ORDER BY CollectedAt DESC LIMIT 4;"
```

**검증 결과 (성공):**

*   `harman`과(와) `harman-m02` 두 노드의 데이터가 교차로 수집됨을 확인했습니다.
*   `filelist`에 `Step 1`에서 생성한 노드별 테스트 파일(`control_plane_file.txt`, `worker_node_data.json` 등)이 정확히 표시됨을 확인했습니다.

| nodename | mountpath | filelist | collectedat |
| :--- | :--- | :--- | :--- |
| harman | /mnt/node-data | ["system.log", "control\_plane\_file.txt"] | 2025-11-11 01:33:10+00 |
| harman-m02 | /mnt/node-data | ["worker\_node\_data.json"] | 2025-11-11 01:32:42+00 |
| harman | /mnt/node-data | ["system.log", "control\_plane\_file.txt"] | 2025-11-11 01:32:10+00 |
| harman-m02 | /mnt/node-data | ["worker\_node\_data.json"] | 2025-11-11 01:31:42+00 |
