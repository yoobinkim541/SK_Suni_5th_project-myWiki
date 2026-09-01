# Hermes Codex CLI 연결

myWiki의 보고서 섹션과 위키 주제 생성은 OpenRouter가 실패했을 때만
Hermes 호스트의 Codex CLI로 한 번 더 시도할 수 있습니다. 문서 분류·신뢰도·중요도
평가 등 대량 분석은 기존 OpenRouter 경로를 유지해 주간 Codex 사용량을 제한합니다.

## stock-report와 같은 실행 경계

`src/llm/codex_cli.py`가 `codex exec`를 subprocess argv 배열로 실행합니다.
프롬프트는 stdin으로 넘기고, `--ephemeral`, `-s read-only`, `-o`를 사용하므로
세션 파일을 남기거나 프로젝트 파일을 수정하지 않습니다. `CODEX_CLI_PATH`로 Hermes에
설치된 실행 파일(또는 래퍼)을 지정할 수 있습니다.

## Hermes 설정

백엔드 Docker 이미지에는 `@openai/codex@0.151.0`가 포함되어 있으므로
컨테이너 안에서 `codex --version`을 바로 확인할 수 있습니다. Hermes VM에서
한 번만 Codex 인증을 완료하고, Compose의 `CODEX_HOST_HOME`을 호스트의
`.codex` 디렉터리로 지정하면 해당 디렉터리가 컨테이너 `/root/.codex`에
읽기 전용으로 연결됩니다. 인증 파일은 이미지나 Git에 포함되지 않습니다.

백엔드 컨테이너의 `.env`에는 다음을 설정합니다.

```env
CODEX_CLI_ENABLED=true
CODEX_CLI_PATH=codex
CODEX_CLI_WORKSPACE=/app
CODEX_HOST_HOME=/home/ubuntu/.codex
CODEX_MODEL=gpt-5.5
CODEX_REASONING=low
CODEX_SANDBOX=read-only
CODEX_CLI_TIMEOUT_SECONDS=180
```

배포 후 `docker compose exec -T api codex --version`으로 실행 파일만 확인합니다.
로그인 토큰 자체는 출력하지 않습니다. Codex CLI 인증이 없거나 설정이 꺼져
있으면 기존 OpenRouter 경로만 사용됩니다.

## 동작 순서

1. 보고서·위키 생성이 OpenRouter 기본 모델을 호출합니다.
2. 기본 모델이 실패하면 OpenRouter fallback 모델을 한 번 시도합니다.
3. 두 호출이 모두 실패하고 `CODEX_CLI_ENABLED=true`이면 Hermes Codex CLI를 호출합니다.
4. Codex도 실패하면 기존과 동일하게 해당 산출물을 실패 상태로 기록합니다.

보고서·위키 스케줄은 GitHub Actions가 `DEPLOY_SSH_*` 시크릿으로 Hermes에 접속한 뒤
컨테이너 안에서 실행하도록 구성되어 있습니다. 따라서 이 두 작업은 Hermes의 Codex
인증을 사용할 수 있습니다. 반면 수집·전처리·분류 같은 대량 데이터 작업은 기존
GitHub runner에 남겨 Codex를 호출하지 않습니다. 단순히 `.env`에 플래그만 추가하면
인증이 생기지는 않으므로, Hermes의 `.codex` 인증 디렉터리와 `CODEX_CLI_ENABLED=true`
설정이 모두 필요합니다.
