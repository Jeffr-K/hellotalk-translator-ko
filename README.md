# HelloTalk Translator

iPhone 보이스룸의 음성을 Mac에서 받아 실시간 자막, 한국어 번역, 문법 추천으로 보여주는 로컬 우선 학습 도구다.

현재 최종 PoC 경로는 다음과 같다.

```text
Mac audio → in-memory PCM → persistent whisper.cpp → FastAPI SSE → React
                                                      └→ Ollama learning notes
```

- 오디오 모달리티와 API: [`modalities/audio`](modalities/audio/README.md)
- React 앱: [`apps/web`](apps/web)
- 최종 PoC 명세: [`docs/realtime-react-sse-poc.md`](docs/realtime-react-sse-poc.md)
- 번역 오류 후속 과제: [`docs/기술적_한계_번역_오류.md`](docs/기술적_한계_번역_오류.md)
- 다자간 대화 후속 과제: [`docs/다자간_대화_화자분리_타임라인.md`](docs/다자간_대화_화자분리_타임라인.md)
