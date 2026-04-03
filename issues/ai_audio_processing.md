### Feature: Implement Kafka Infrastructure & AI Audio Processing Pipeline

**Problem**
FluentMeet's core value proposition — real-time voice translation in video calls — requires a low-latency, fault-tolerant pipeline for processing audio as it streams. Orchestrating Speech-to-Text (STT), Translation, and Text-to-Speech (TTS) synchronously within a single request or WebSocket handler would be fragile, unscalable, and far too slow. There is currently no messaging infrastructure to decouple these processing stages from one another.

**Proposed Solution**
Set up Apache Kafka as the central message bus for the audio processing pipeline. Each stage of the pipeline (ingest → STT → translation → TTS → egress) becomes an independent, async worker that consumes from one Kafka topic and produces to the next. This architecture allows each stage to be scaled, monitored, and replaced independently, while providing natural backpressure and replay capabilities via Kafka's offset management.

**Pipeline Architecture**

```
[WebSocket Audio Ingest]
        │
        ▼
  audio.raw  ──► STTWorker (Deepgram) ──► text.original
                                               │
                                               ▼
                                    TranslationWorker (DeepL/GPT) ──► text.translated
                                                                            │
                                                                            ▼
                                                                 TTSWorker (Voice.ai) ──► audio.synthesized
                                                                                               │
                                                                                               ▼
                                                                                    [WebSocket Audio Egress]
```

**User Stories**
*   **As a meeting participant,** I want to hear the speaker's voice translated in near real-time, so I can follow the conversation without language barriers.
*   **As a developer,** I want each processing stage to be an independently deployable worker, so I can scale the bottleneck stages (e.g., STT) without over-provisioning the others.
*   **As a DevOps engineer,** I want all pipeline failures to be logged with the original message retained in the topic, so I can diagnose issues and replay failed messages without data loss.

**Acceptance Criteria**
1.  A Kafka cluster is configured and reachable from the FastAPI application (via `docker-compose` for local development).
2.  The following Kafka topics are created and documented:
    *   `audio.raw` — raw audio chunks from the WebSocket ingest.
    *   `text.original` — transcribed text output from the STT worker.
    *   `text.translated` — translated text output from the Translation worker.
    *   `audio.synthesized` — synthesized audio output from the TTS worker.
3.  `AudioIngestService` is implemented in `app/services/audio_bridge.py` to accept streaming audio from the WebSocket and publish chunks to `audio.raw`.
4.  `STTWorker` consumes from `audio.raw`, calls the Deepgram API for transcription, and publishes results to `text.original`.
5.  `TranslationWorker` consumes from `text.original`, calls the DeepL or GPT API for translation, and publishes results to `text.translated`.
6.  `TTSWorker` consumes from `text.translated`, calls the Voice.ai API for speech synthesis, and publishes the resulting audio to `audio.synthesized`.
7.  The WebSocket audio egress handler consumes from `audio.synthesized` and streams the translated audio back to the correct meeting room participants.
8.  All workers handle transient errors gracefully (retry with backoff) and log pipeline latency per stage.
9.  Each worker is independently horizontally scalable via Kafka consumer groups.
10. End-to-end pipeline latency is measured and logged for each audio chunk (from `audio.raw` publish to `audio.synthesized` consume).

**Proposed Technical Details**
*   **Kafka Client**: `aiokafka` for all async producer and consumer operations.
*   **Kafka Config**: `KAFKA_BOOTSTRAP_SERVERS` already defined in `app/core/config.py`.
*   **Topic Schema**: Each message carries a `room_id`, `user_id`, `sequence_number`, and the payload (binary audio or UTF-8 text), enabling correct reassembly and routing.
*   **Worker lifecycle**: All workers are started as background tasks within FastAPI's `lifespan` context manager, ensuring clean startup and shutdown.
*   **Consumer Groups**:
    *   `stt-worker-group`
    *   `translation-worker-group`
    *   `tts-worker-group`
*   **New Service Files**:
    *   `app/services/audio_bridge.py` — `AudioIngestService` (producer) and egress router.
    *   `app/services/stt_worker.py` — `STTWorker` consumer.
    *   `app/services/translation_worker.py` — `TranslationWorker` consumer.
    *   `app/services/tts_worker.py` — `TTSWorker` consumer.
*   **Infrastructure**: `infra/docker-compose.yml` extended with `zookeeper` and `kafka` services.

**Tasks**
- [ ] Add Zookeeper and Kafka services to `infra/docker-compose.yml`.
- [ ] Create and document the four Kafka topics (`audio.raw`, `text.original`, `text.translated`, `audio.synthesized`) with appropriate partition and retention settings.
- [ ] Define the standard Kafka message envelope schema (Pydantic model) in `app/schemas/pipeline.py`.
- [ ] Implement `AudioIngestService` in `app/services/audio_bridge.py` to publish raw audio chunks.
- [ ] Implement `STTWorker` in `app/services/stt_worker.py` using the Deepgram SDK.
- [ ] Implement `TranslationWorker` in `app/services/translation_worker.py` using the DeepL or OpenAI API.
- [ ] Implement `TTSWorker` in `app/services/tts_worker.py` using the Voice.ai API.
- [ ] Implement the WebSocket audio egress handler to stream `audio.synthesized` back to room participants.
- [ ] Register all workers as background tasks in the FastAPI `lifespan` context in `app/main.py`.
- [ ] Add per-stage latency logging and end-to-end pipeline latency metrics.
- [ ] Write unit tests for each worker (mock Kafka producer/consumer and AI API calls).
- [ ] Write an integration test verifying a chunk flows end-to-end from `audio.raw` to `audio.synthesized`.

**Open Questions/Considerations**
*   Which STT provider will be primary — Deepgram or OpenAI Whisper? Do we need to support fallback?
*   What is the acceptable end-to-end pipeline latency target (e.g., < 500ms from speech to translated audio)?
*   How many Kafka partitions should each topic have to achieve the desired throughput? This depends on the expected number of concurrent meeting rooms.
*   Should we implement a dead-letter topic (e.g., `pipeline.dlq`) for messages that fail processing after N retries?
*   How will we handle speaker diarization — do we need to preserve per-speaker audio streams through the pipeline?