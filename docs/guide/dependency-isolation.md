# Dependency Isolation: Version Conflicts and Multi-Environment Patterns

This document covers how envknit handles package versioning, dependency isolation,
and the practical limits of Python's import system.

---

## 1. 버전 constraint vs 실제 설치 버전

`envknit.yaml`에 `requests>=2.28`처럼 지정하는 것은 **resolver에게 주는 제약 조건**이지,
그 범위의 모든 버전을 설치하는 것이 아닙니다.

```
envknit.yaml:         requests>=2.28        ← "최소 2.28 이상이면 됨"
                          ↓
uv pip compile        resolver가 PyPI에서 최신 호환 버전 선택
                          ↓
envknit.lock.yaml:    requests==2.32.5      ← 정확한 버전으로 고정 (pin)
                          ↓
envknit install       requests 2.32.5 하나만 설치
```

**설치되는 건 lock에 기록된 단 하나의 버전입니다.**

### lock 파일이 핵심

```yaml
# envknit.lock.yaml
environments:
  default:
    - name: requests
      version: 2.32.5    # ← 이 버전만 설치됨
```

lock 파일이 한번 생성되면 이후 `envknit install`은 constraint를 다시 보지 않고
lock의 고정 버전만 사용합니다.

### 버전이 바뀌는 시점

| 명령 | 결과 |
|---|---|
| `envknit lock` | constraint 재평가 → 그 시점 최신 호환 버전으로 lock 갱신 |
| `envknit lock --update requests` | requests만 재resolve |
| `envknit install` | lock 그대로 설치 (constraint 무시) |

---

## 2. 특정 버전 설치 및 전환

### 특정 버전 설치

```yaml
# envknit.yaml
environments:
  default:
    packages:
      - requests==2.28.2    # 정확히 이 버전만
```

`==`으로 pin하면 uv resolver가 다른 선택지 없이 그 버전을 lock에 기록합니다.

### 이후 다른 버전으로 전환

**방법 1 — yaml 수정 후 재lock**
```yaml
packages:
  - requests==2.31.0    # 버전 변경
```
```bash
envknit lock --update requests
envknit install
```

**방법 2 — 환경별로 다른 버전 공존**
```yaml
environments:
  legacy:
    packages:
      - requests==2.28.2
  default:
    packages:
      - requests==2.32.5
```

이것이 envknit의 핵심 가치입니다. `~/.envknit/packages/requests/2.28.2/`와
`~/.envknit/packages/requests/2.32.5/`가 global store에 **동시에** 존재하고,
`use("legacy")`/`use("default")` 호출 시점에 PYTHONPATH를 전환합니다.

---

## 3. 런타임에서 버전 활성화

`envknit.yaml`의 버전 고정과 런타임 활성화는 **역할이 다릅니다.**

| | 역할 | 없으면? |
|---|---|---|
| `envknit.yaml` `==2.28.2` | resolver에게 "이 버전으로 lock 생성" | lock에 다른 버전이 기록됨 |
| `envknit.enable("default")` | 런타임에 PYTHONPATH를 실제로 전환 | 시스템 Python 환경이 사용됨 |

### `envknit.enable()` 없이 실행하면

```python
# envknit.yaml에 requests==2.28.2 고정했어도...
import requests
print(requests.__version__)  # 시스템에 설치된 버전 출력 (예: 2.32.5)
```

`envknit.yaml`/lock 파일은 `~/.envknit/packages/` 아래 패키지를 설치하는 기준일 뿐,
Python 프로세스의 import 경로에 자동으로 개입하지 않습니다.

### 활성화 방법 3가지

**방법 1 — 코드에서 `enable()` (단일 환경 고정)**
```python
# main.py 맨 위에 한 줄
import envknit; envknit.enable("default")

# 이후 모든 파일에서 별도 설정 없이
import requests  # lock에 고정된 버전
```

**방법 2 — `use()` context manager (스크립트별 전환)**
```python
with envknit.use("legacy"):
    import requests
    print(requests.__version__)  # 2.28.2

with envknit.use("default"):
    import requests
    print(requests.__version__)  # 2.32.5
```

**방법 3 — CLI `envknit run` (비침투적)**
```bash
envknit run --env default -- python main.py
```

`envknit run`은 `PYTHONPATH`를 주입한 채 subprocess를 실행하므로
코드에 `envknit` import가 전혀 없어도 됩니다. 기존 레거시 코드에 적용할 때 유용합니다.

---

## 4. 같은 프로세스, 다른 버전 — sys.modules 충돌

같은 프로세스에서 **동일 패키지의 두 버전을 동시에 활성화**하면 `sys.modules` 충돌이 발생합니다.

```python
# ❌ 위험 — 같은 프로세스에서 requests를 두 버전으로 import
with envknit.use("legacy"):
    import requests as req_old   # 2.28.2 — sys.modules["requests"] 등록됨

with envknit.use("default"):
    import requests as req_new   # ⚠️ 이미 캐시됨 → 2.28.2가 반환될 수 있음
```

Python의 `sys.modules`는 프로세스 전역 캐시입니다. 한 번 `import requests`가
실행되면 이후 동일 프로세스의 모든 `import requests`는 캐시에서 반환됩니다.

### 올바른 해결책

```python
# ✅ 안전 — 각각 별도 프로세스
old_result = envknit.worker("legacy").run("import requests; output = requests.__version__")
new_result = envknit.worker("default").run("import requests; output = requests.__version__")
```

---

## 5. 한 환경, 다른 프로세스 — 완전히 안전

프로세스가 다르면 `sys.modules`도 완전히 분리됩니다.

```
프로세스 A (worker "v1")          프로세스 B (worker "v2")
─────────────────────────         ─────────────────────────
PYTHONPATH:                       PYTHONPATH:
  ~/.envknit/packages/            ~/.envknit/packages/
    dep-x/1.2.0/                    dep-x/2.5.0/
    package-a/1.0.0/                package-a/2.0.0/

sys.modules["dep_x"] = 1.2.0     sys.modules["dep_x"] = 2.5.0
                                  (완전히 독립된 메모리 공간)
```

프로세스는 OS 레벨에서 메모리가 분리되므로 `sys.modules` 충돌 자체가 불가능합니다.

```python
# 두 버전을 병렬로 동시 실행
with envknit.worker("v1") as w1, envknit.worker("v2") as w2:
    f1 = w1.submit("import package_a; output = package_a.process(data)")
    f2 = w2.submit("import package_a; output = package_a.process(data)")

    result_v1 = f1.result()  # dep-x 1.2.0 사용
    result_v2 = f2.result()  # dep-x 2.5.0 사용
```

### global store가 이를 가능하게 하는 이유

```
~/.envknit/packages/
  dep-x/
    1.2.0/    ← 프로세스 A가 참조
    2.5.0/    ← 프로세스 B가 참조 (동시에, 충돌 없음)
```

파일 시스템은 read-only 공유에 대해 완전히 안전합니다. 여러 프로세스가 동일
디렉토리를 동시에 읽어도 충돌이 없습니다. virtualenv가 환경마다 파일을 복사하는
것과 달리, envknit global store는 "설치는 한 번, 참조는 여러 프로세스에서" 동시에
가능합니다.

---

## 6. A의 코드를 B에서 import할 때 의존성 충돌

"A의 코드를 B에서 import한다"는 것은 결국 **모듈(파일)을 import**하는 것입니다.

```python
# module_a.py — package_x 1.0.0 기준으로 작성된 코드
import package_x
def do_something():
    return package_x.old_api()
```

```python
# script_b.py — A를 import하면서 package_x 2.0.0도 쓰고 싶음
import module_a        # 이 순간 package_x 1.0.0이 sys.modules에 등록됨
import package_x       # ⚠️ 캐시 히트 → 1.0.0 반환 (2.0.0 아님)

package_x.new_api()    # 2.0.0에만 있는 API → AttributeError
```

`import module_a`가 실행되는 순간 module_a의 의존성이 현재 프로세스에 고정됩니다.

### 해결 방법

**방법 1 — worker로 A를 격리 (권장)**

```python
# script_b.py
import envknit

# A의 코드는 v1 환경 프로세스에서만 실행
result = envknit.worker("v1").run("""
import module_a
output = module_a.do_something()
""")

# B 자신은 v2 환경 사용
with envknit.use("v2"):
    import package_x        # 2.0.0
    package_x.new_api()
```

**방법 2 — SubInterpreterEnv (같은 프로세스, 다른 interpreter)**

```python
with envknit.SubInterpreterEnv("v1") as interp:
    result = interp.eval_json("""
import module_a
result = module_a.do_something()
""")
# 이 interpreter의 sys.modules는 메인 프로세스와 독립
```

### 프로세스 간 데이터 전달

`worker()`의 반환값은 JSON으로 제한됩니다. 프로세스 간에는 Python 객체를 직접
전달할 수 없고, 직렬화 가능한 데이터(dict, list, str, int)만 오갈 수 있습니다.

| 의도 | 실제 구현 | envknit 지원 |
|---|---|---|
| A의 **코드**를 B에서 실행 | 같은 파일을 다른 PYTHONPATH로 import | `use()` / `worker()` |
| A의 **결과값**을 B에서 사용 | IPC (JSON 직렬화) | `worker().run()` 반환값 |
| A와 B가 **실시간 통신** | socket, queue, pipe | envknit 범위 밖 |

---

## 7. 의존성 충돌이 중첩될 때

```
script_b.py
├── import module_a  (package_x 1.0.0 필요)
│   └── module_a imports module_c  (package_y 3.0.0 필요)
├── import package_x 2.0.0  ← 충돌
└── import package_y 4.0.0  ← 충돌
```

프로세스 하나에서 해결이 불가능합니다.

### 해결 전략

**전략 1 — 충돌하는 서브트리를 worker로 격리**

```python
# 충돌하는 서브그래프 전체를 하나의 worker 안에 가둠
result_a = envknit.worker("env_for_a").run("""
import module_a        # package_x 1.0.0 + package_y 3.0.0
import module_c
output = module_a.do(module_c.prepare())
""")

# 메인 프로세스는 자신의 버전만 사용
import package_x   # 2.0.0
import package_y   # 4.0.0
```

**전략 2 — 환경 설계 단계에서 충돌 그룹 분리 (근본 해결)**

```yaml
# envknit.yaml
environments:
  legacy_pipeline:
    packages:
      - module-a      # package_x 1.0.0 당김
      - module-c      # package_y 3.0.0 당김

  modern_pipeline:
    packages:
      - package_x==2.0.0
      - package_y==4.0.0
```

충돌 가능성이 있는 코드를 처음부터 환경으로 분리하는 것이 가장 안정적입니다.

**전략 3 — 중첩이 깊어지면 마이크로서비스로**

중첩이 3단계 이상이면 worker 중첩보다 독립 서비스(HTTP API, gRPC 등)로 분리하는
것이 현실적입니다.

### 깊이별 권장 접근

```
충돌 깊이 1단계  →  worker() 로 해결 가능
충돌 깊이 2단계  →  환경 설계(yaml)로 미리 분리 권장
충돌 깊이 3단계+ →  아키텍처 재설계 (마이크로서비스, API 경계)
```

---

## 8. 패턴 결정 가이드

| 상황 | 권장 방법 |
|---|---|
| 단일 환경, 버전 고정 | `envknit.enable()` 또는 `envknit run` |
| 스크립트별 순차 전환 | `use()` context manager |
| 동일 패키지 두 버전 동시 사용 | `worker()` subprocess |
| 같은 프로세스, C extension 포함 | `SubInterpreterEnv` |
| 중첩 의존성 충돌 | 환경 설계 분리 → worker 격리 |
| 충돌 3단계 이상 | 마이크로서비스 분리 |

---

## 9. Python import 시스템의 근본적 한계

Python의 import 시스템은 패키지를 **이름 단위로** 캐시합니다. `dep_x`라는 이름의
모듈은 버전에 관계없이 하나만 존재할 수 있습니다.

Java의 ClassLoader나 Node.js의 `require()`(경로 기반)와 달리, Python은 동일 이름
패키지의 다중 버전을 같은 프로세스에서 공존시키는 공식 메커니즘이 없습니다.

Node.js는 `node_modules` 중첩으로 패키지마다 다른 버전을 허용해서 이 문제를
회피했지만 대신 디스크 낭비와 `node_modules` 블랙홀이 생겼습니다. Python은 그
선택을 하지 않았고, 결국 **프로세스 경계가 유일한 실용적 격리 수단**입니다.

`SubInterpreterEnv`(Gen 2)가 interpreter 레벨에서 이를 우회하는 시도이지만,
C extension 호환성 문제로 아직 제약이 있습니다.

envknit의 `worker()` 모델은 이 경계를 명시적으로 다루며, 실질적으로
**microservice 아키텍처를 프로세스 레벨에서 구현**하는 것과 동일합니다.
각 worker는 독립된 의존성 스택을 가진 독립 서비스처럼 동작하고,
오케스트레이터는 JSON으로 통신합니다.
