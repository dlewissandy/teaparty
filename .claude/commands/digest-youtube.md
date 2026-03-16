# Digest: YouTube Sources

Fetch new videos and transcripts from YouTube channels and write partial digest results.

**This skill is called by `/intake` as part of a parallel fan-out. Do not run standalone.**

## What To Do

1. **Load state:**
   ```python
   from intake.state import load_state
   state = load_state()
   last_run = state.get('last_run', '')
   ```

2. **Fetch recent videos from these channels** using `intake/youtube.py`:

   | Channel | URL |
   |---------|-----|
   | David Shapiro | https://www.youtube.com/@DavidShapiroAutomator |
   | AI Explained | https://www.youtube.com/@aiexplained-official |
   | Andrej Karpathy | https://www.youtube.com/@AndrejKarpathy |
   | Dwarkesh Patel | https://www.youtube.com/@DwarkeshPatel |

   ```python
   from intake.youtube import digest_channel
   results = digest_channel(channel_url, max_videos=3, since=last_run)
   ```

3. **For each video with a transcript**, extract:
   - **Key ideas** — 2-5 most important concepts from the transcript
   - **Techniques and methods** — novel approaches discussed
   - **Results and evidence** — what was demonstrated or claimed
   - **Quotes** — 1-3 verbatim quotes from the transcript with speaker attribution
   - **Relevance signal** — one sentence on why this matters for agent coordination

4. **Write results** to `intake/digests/.partial-youtube-<YYYY-MM-DD>.md` using the digest entry format:
   ```markdown
   ## <N>. <Title>
   **Source:** <channel name>
   **URL:** <video url>
   **Type:** video
   **Published:** <date>

   ### Key Ideas
   - ...
   ### Techniques & Methods
   - ...
   ### Results & Evidence
   - ...
   ### Notable Quotes
   > "..." — <speaker>
   ### Relevance Signal
   <one sentence>
   ```

5. **Track what was processed** — at the end of the file, append:
   ```markdown
   <!-- PROCESSED
   channel_url|video_id|published_date
   -->
   ```

## Important
- Only process videos published after `last_run` date from state.
- Transcripts are capped at 15,000 chars by default — the intro and conclusion are preserved.
- If a channel has no new videos, skip it silently.
- If no new videos found across all channels, write a file containing only `<!-- NO NEW CONTENT -->`.
