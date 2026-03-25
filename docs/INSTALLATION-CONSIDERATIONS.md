# EnvKnit 설치 방식 고민사항

## 문제 정의

EnvKnit는 Python 패키지 의존성을 관리하는 도구인데, EnvKnit 자체도 Python으로 작성되어 pip로 설치된다. 이로 인해 발생하는 순환 구조 문제.

```
Python (시스템)
  └── pip install envknit
            └── envknit가 pip/conda 관리
                  └── pip install numpy
                        └── 또 pip 사용
```

**질문**: EnvKnit가 자기 자신을 관리하면 안 되는가?

---

## 다른 도구들의 접근 방식

| 도구 | 언어 | 접근 방식 |
|------|------|-----------|
| **pyenv** | Shell + C | Python 없이 Python 버전 관리 |
| **nvm** | Shell | Node 없이 Node 버전 관리 |
| **rustup** | Rust | Rust 자체로 설치, 독립적 |
| **conda** | Python | base 환경에 설치, 다른 환경과 분리 |
| **poetry** | Python | 프로젝트 내 의존성만 관리 |
| **pipx** | Python | CLI 도구용 격리 환경 제공 |

---

## Conda의 구조 (상세)

```
Anaconda/Miniconda 설치
  │
  ├── base 환경 (Python + conda 패키지)
  │     └── conda CLI (/opt/.../bin/conda)
  │
  └── 다른 환경들
        └── conda create -n myenv
              └── 독립적인 Python + 패키지들
```

**Conda의 핵심:**
- Conda는 base 환경 안에 있음
- Conda가 다른 환경을 생성할 때, 자신의 base와 분리된 환경 생성
- 즉, conda는 "자신이 설치된 환경"과 "관리하는 환경"이 완전히 분리됨

**EnvKnit와의 차이:**
- Conda: Anaconda/Miniconda가 먼저 설치되어야 함
- EnvKnit: pip로 설치 가능하지만 순환 문제 발생

---

## 해결 방안 옵션

### 옵션 A: pipx/전용환경 강제 + 문서화

```bash
# 사용자 머신에서
pipx install envknit

# 또는 전용 가상환경
python3 -m venv ~/.envknit/venv
~/.envknit/venv/bin/pip install envknit
export PATH="$HOME/.envknit/venv/bin:$PATH"
```

**장점:**
- 설치 간단
- 기존 pip 생태계 활용

**단점:**
- 여전히 순환 구조
- 근본적 해결이 아님

---

### 옵션 B: 독립 실행형 바이너리 (PyInstaller)

```
┌─────────────────────────────────────────────┐
│  envknit (단일 바이너리)                    │
│  ├── Python 인터프리터 (내장)               │
│  ├── envknit 코드 (내장)                    │
│  └── 모든 의존성 (내장)                     │
│                                              │
│  → Python 없이 실행 가능                    │
└─────────────────────────────────────────────┘
          │
          ▼ 호출
┌─────────────────────────────────────────────┐
│  외부 conda/pip/poetry 명령만 실행          │
│  (subprocess)                                │
└─────────────────────────────────────────────┘
```

**장점:**
- Python 없는 머신에서도 실행
- 시스템 Python 영향 없음
- 깔끔한 분리

**단점:**
- 바이너리 크기 큼 (30-50MB)
- 플랫폼별 빌드 필요 (macOS Intel/ARM, Linux, Windows)
- 배포 복잡

---

### 옵션 C: Shell 진입점 + Python 코어

```
┌─────────────────────────────────────────────┐
│  envknit (shell script)                     │
│  #!/bin/bash                                │
│  exec python3 -m envknit "$@"               │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│  envknit Python 모듈                        │
│  (시스템 Python으로 실행됨)                 │
└─────────────────────────────────────────────┘
```

**설치 방식:**
```bash
# Homebrew
brew install envknit

# curl
curl -sSL https://envknit.dev/install.sh | sh

# pip (여전히 가능)
pip install envknit
```

**장점:**
- 설치 간편
- Homebrew 배포 가능
- 유연함

**단점:**
- 여전히 Python 필요
- 부분적 순환

---

## 옵션 비교

| 옵션 | 순환 문제 | 설치 복잡도 | 배포 방식 |
|------|-----------|-------------|-----------|
| A. 전용환경 | ⚠️ 여전히 있음 | 간단 | pip |
| B. 바이너리 | ✅ 해결 | 복잡 | GitHub Releases |
| C. Shell+Python | ⚠️ 부분적 | 중간 | Homebrew, curl |

---

## 권장 방향

### v0.1.x (현재 — Rust CLI)
- 독립 바이너리 배포 완료 (PyInstaller, GitHub Releases)
- `envknit run` 기반 런타임 격리 제공

### 미래
- Homebrew formula 검토
- Shell 설치 스크립트 (`curl | sh`) 제공

---

## 참고: activate/deactivate 대체

`activate`/`deactivate` 명령은 제거되었습니다. 런타임 격리는 `envknit run` 또는
Python 라이브러리의 `envknit.use()` / `envknit.enable()` 으로 대체됩니다.

---

## 지원 백엔드

| 백엔드 | 상태 | 설명 |
|--------|------|------|
| conda | ✅ | 기본 백엔드 |
| pip | ✅ | conda 없이 사용 가능 |
| poetry | ✅ | Poetry 프로젝트 지원 |

---

## 결론

1. **EnvKnit는 순환 구조를 가짐** - Python으로 작성된 패키지 관리자
2. **바이너리 배포로 독립성 확보** - 시스템 Python 영향 최소화
3. **`envknit run`으로 런타임 격리** - 명시적 활성화 제공
4. **다중 백엔드 지원** - conda, pip, poetry
