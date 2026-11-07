# Process Replay & Monitoring

1. Open a local L5 workspace and select **Monitoring**. Choose an original dataset, or open **Models**, run a simulation, select **Save as Dataset**, and follow **Replay and monitor**.
2. Select 1–12 signals and enter two windows in dataset-native seconds. Confirm that the earlier window represents normal operation. It must have complete measurements for the selected signals and enough rows for the chronological 70% fit and 30% calibration split to contain at least 30 rows each.
3. Select Robust Max-Z, PCA-Q (two or more signals), EWMA, or Page CUSUM. Choose calibration alpha and how many consecutive exceedances confirm an alarm. Select **Prepare replay**, then **Start**.
4. Change playback speed, pause or resume, or move the playhead and select **Seek**. **Restart** returns the console to the ready state at the beginning. The score and selected signal share a timeline of the latest 360 observations. Select an alarm to pause at the current observation and see measurements and contributions around its peak.
5. **Save alarm as incident** stores the calculated analysis through the current observation and links the selected interval to a persistent incident. Open it to add evidence, inspect the source, or generate the existing incident report. **Export replay JSON** downloads the observed prefix, including measurements, timestamps, decisions, thresholds, alarm intervals and contributions, detector parameters, and the source dataset's ID and checksums. The playback console itself is temporary.

For a repeatable example, run **Coupled-Tank** with **Tank 1 leak** beginning at 60 s, an 85 s duration, a 0.2 s sample interval, and seed 17. Save the run as a Dataset. Monitor the first two level signals with Robust Max-Z, using 0–55 s for normal training and 55.2–85 s for replay. Set alpha to 0.05 and try 5× playback.

## Score and alarm semantics

- Replay uses stable timestamp order. Equal timestamps keep their source row order and are delivered at the same playhead time. Irregular spacing determines how long playback waits between observations. EWMA and CUSUM update once per acquired observation using their existing recurrences.
- The detector is frozen before the first replay observation. Calibration starts with fresh temporal state and uses the sorted score at zero-based index `ceil((n − 1) × (1 − alpha))`. The replay also starts with fresh state. Future false-alarm rates depend on process conditions and sample dependence.
- A score strictly greater than the threshold counts toward persistence. Alarm onset is the observation that confirms persistence. The first later score at or below the threshold records recovery. A row with a missing selected measurement has no reported score, resets temporal state and persistence, and marks any active alarm interrupted.
- The alarm's observed span is the time from confirmation to the last alarming observation. A single-observation alarm has a span of zero. Recovery and interruption timestamps are recorded separately. The process state between observations is unknown.
- Backward seeks show only the prefix at the requested time. Replaying it or changing speed yields the same scores and alarms. Contributions rank the detector's statistical deviations at the alarm peak.
- Training and replay use separate windows from the same saved dataset. Replay accepts up to 100,000 observations. Transformation outputs may contain values computed from future measurements and are excluded. The workspace uses the local L5 server and historical measurements.
