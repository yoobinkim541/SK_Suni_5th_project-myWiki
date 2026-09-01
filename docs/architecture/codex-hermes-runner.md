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

Hermes VM에서 한 번만 Codex 인증을 완료한 뒤, 백엔드 컨테이너의 `.env`에 다음을 설정합니다.

```env
CODEX_CLI_ENABLED=true
CODEX_CLI_PATH=codex
CODEX_CLI_WORKSPACE=/app
CODEX_MODEL=gpt-5.5
CODEX_REASONING=low
CODEX_SANDBOX=read-only
CODEX_CLI_TIMEOUT_SECONDS=180
```

컨테이너 안에서 `codex --version`과 `codex login`이 동작하지 않는 배포라면
`CODEX_CLI_PATH`를 호스트 Codex CLI를 호출하는 검증된 래퍼로 지정해야 합니다.
Codex CLI가 없는 환경에서는 설정을 켜도 기존 OpenRouter 경로만 사용됩니다.

## 동작 순서

1. 보고서·위키 생성이 OpenRouter 기본 모델을 호출합니다.
2. 기본 모델이 실패하면 OpenRouter fallback 모델을 한 번 시도합니다.
3. 두 호출이 모두 실패하고 `CODEX_CLI_ENABLED=true`이면 Hermes Codex CLI를 호출합니다.
4. Codex도 실패하면 기존과 동일하게 해당 산출물을 실패 상태로 기록합니다.

GitHub Actions의 스케줄러는 여전히 GitHub runner에서 실행됩니다. 따라서 Codex 경로를
실제로 사용하려면 스케줄 작업을 Hermes에서 실행하거나, Actions가 Hermes의 검증된
래퍼를 호출하도록 별도 배포해야 합니다. 단순히 `.env`에 플래그만 추가하면 Actions
runner에 Codex 인증이 생기지는 않습니다.


