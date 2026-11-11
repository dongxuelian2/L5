# Live Data: OPC UA

Live Data records read-only OPC UA subscriptions into the active L5 workspace. The collector runs in the Python server; closing the browser, changing pages or pausing the chart does not stop recording.

## Run the coupled-tank demo

Install the normal project requirements and build/start L5 as described in the [README](../README.md#quick-start). In another terminal at the repository root, run:

```sh
node scripts/python.mjs -m examples.opcua_tanks --interval 0.2 --fault sensor_bias --fault-at 30 --bad-quality-at 45 --interrupt-at 55
```

1. Open an L5 workspace in the local browser and choose **Live Data**. Connect to `opc.tcp://127.0.0.1:4840/l5/tanks/` using the anonymous **None** mode. Under **Objects → Coupled Tanks**, browse the tank levels, flows and pump or valve readings. Read a current value or add variables to the recording.
2. Set the sampling and publishing intervals before connecting. For the demo, 100 ms sampling and 200 ms publishing work well. Start a recording and observe the quality and connection events. The demo applies a level bias, injects bad quality and stops/restarts its OPC UA listener. Run `node scripts/python.mjs -m examples.opcua_tanks --help` to adjust the timings.
3. Stop the recording. Open it again from session history, choose a time range if needed, and create a Dataset. Inspect the result in **Signals** or run **Robust Max-Z** on the biased level signal in the normal analysis workflow. Start recording early in the normal segment and choose a baseline ending before the fault; the detector needs at least 30 fit and 30 calibration rows (100 baseline rows with the default 70/30 split). Analyze a later interval that includes the fault. Use a single level channel for this first run; independent channels can have different source clocks.

The demo uses the existing coupled-tank simulation and listens on loopback. It can write its own simulated variables; the L5 client uses only discovery, reads and subscriptions. For a reproducible test of the full workflow, including a detector on saved data, run `node scripts/python.mjs -m unittest discover -s tests -p test_live_gateway.py -v`.

## Connect to equipment

Use an `opc.tcp://` address reachable by the Python process. For a trusted development endpoint, **None** supports anonymous access. For equipment, use **Sign & Encrypt** with Basic256Sha256, the client's certificate and private key, the matching client Application URI, and the expected server certificate acquired through a trusted channel. **Sign** is also supported for anonymous connections where confidentiality is unnecessary. Configure the server to trust the client certificate and grant read-only access. User/password credentials require **Sign & Encrypt**. Paths refer to files on the L5 host; passwords and key material are held in memory and never written to session storage. L5 does not automatically accept a server certificate or fall back to weaker security.

Live API requests must come through a loopback interface and use a loopback Host. Keep the L5 UI local and run one L5 process per data directory. On restart, completed recordings remain readable; enter any credentials again to start a new connection.

## Session evidence and Datasets

- Each recording snapshots the endpoint, requested intervals and mappings. Choose a variable explicitly, edit its display name and unit, and optionally link it to an existing workspace signal. Otherwise the workspace, endpoint and node identify a stable live signal. Exported columns appear in the Signal Catalog with the **OPC UA** source and lineage to the recording.
- Each DataValue retains its value, OPC UA status code/name, source and server timestamps if supplied, and the collector's UTC receipt time. For chronological views use source, then server, then receipt time; the record identifies the chosen clock. The value and quality are independent. A bad or uncertain reading is evidence, even if the server sent a number.
- SQLite stores batches of observations and events in the workspace database. The live view orders by timestamp with arrival ID as a tie-breaker. Duplicate and late arrivals remain available in raw evidence and have explicit diagnostics. The subscription records interruptions and reconnects with backoff from 0.5 to 8 seconds. It starts a fresh subscription after reconnect; missing history is not backfilled. An advisory sampling gap means no changes arrived recently; a steady value can be quiet while its subscription is healthy.
- The client requests a 64-entry queue per monitored item. The local queue holds up to 4,096 observations by default (configurable). When it fills, the collector drops new arrivals and records the count and time span; it commits up to 512 observations per batch. Server queue overflow and missing publish messages have separate events. The exact number of affected measurements on the server is unknown. Scalar payloads are bounded; arrays, structured or oversized values are marked as unsupported or invalid in the session. Stop flushes the queue before finalizing. If L5 is killed or storage fails, committed rows are recoverable; the session reports the interruption or storage failure and cannot assert the number of uncommitted rows.
- Creating a Dataset joins the chosen UTC interval by exact timestamp and uses the last arrival per signal/timestamp. Only good scalar numeric values are projected; Boolean values become 0/1, and integers outside the exact IEEE double range stay in the raw session. Unobserved or invalid cells are blank, and channels with no usable values in the interval are left out. The conversion does not carry values forward or invent rows during an outage. For asynchronous channels, use the Transformation workspace to choose an explicit resampling policy before a multichannel or temporal analysis. Large recordings can be converted in shorter intervals.

The Dataset works with Signal Explorer, detectors, Experiments and Incidents. Its acquisition metadata points to the session containing the raw samples and events.

## Read measurements from another L5 component

Use the existing local API under `/api/workspaces/{workspace_id}/live`. `GET /sessions` lists saved and active sessions. `GET /sessions/{id}/samples?limit=1000` returns the recent chronological tail, with a separate event array. Add ISO `start` and `end` bounds to inspect a historical interval or `include_latest=1` for each mapping's latest observation in that interval. Events use the L5 host's receipt clock.

For a continuous consumer, start at `after_id=0&after_event_id=0`, then advance each cursor to its last returned ID independently. Cursor pages are in arrival order and include late records even when their observation timestamps are older. Process quality before converting to detector input; treat interruption and loss events as coverage breaks. Read the session mappings for signal identity and units. A stopped session remains readable through the same API.

See the [OPC UA MonitoredItem model](https://reference.opcfoundation.org/specs/OPC-10000-4/5.13.1) for the distinction between sampling, publishing and server-side notification queues.
