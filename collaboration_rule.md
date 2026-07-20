# SK mySUNI myWIKI

## 협업 규칙 (Collaboration Rules)
아래의 규칙을 확인하고 준수해 주세요

## 브랜치 전략 (Branching Strategy)
- main : 제품 출시 및 배포용 브랜치 (직접 commit 금지)
- develop : 다음 버전을 개발하는 통합 브랜치
- feature/기능명 : 새로운 기능을 개발하는 브랜치 (예시 : feature/login)
- fix/버그명 : 버그를 수정하는 브랜치 (예시 : fix/error-404)

## 커밋 메시지 규칙(Commit Message Convention)
커밋 메시지는 타입 : 메시지 내용 형태로 작성해주세요
| 타입 | 의미 |
|---|---|
| Feat | 새로운 기능 추가 |
| Fix | 버그 수정 |
| Docs | 문서 수정(README 등) |
| Style | 코드 포맷팅, 세미콜론 누락 등(코드 변경 없는 경우) |
| Refactor | 코드 리팩토링 |

## 풀 리퀘스트 규칙(Pull Request Rules)
1. feature 브랜치 작업 완료 후 develop 브랜치로 PR 을 보냅니다.
2. 충돌(Conflict) 발생 시 작업자가 직접 해결 후 push 합니다.
