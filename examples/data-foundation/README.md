# Signal Workspace example sources

These files contain simulated measurements for a motor cooling system.

| File | Import time configuration | Signal metadata |
|---|---|---|
| `temperature-1s.csv` | Auto or ISO date/time; timestamps include +08:00 | Motor temperature, °C, Temperature, device Motor A |
| `flow-2s-unix-ms.csv` | Unix epoch time, milliseconds | Cooling flow, m³/h, Flow, device Motor A |
| `pressure-irregular.csv` | Select `seconds`; relative numeric seconds | Feed pressure, kPa, Pressure, device Motor A |

The first two sources share a UTC clock. The pressure source uses an independent recorder. In Signal Explorer, set the temperature dataset as the pressure clock's reference, with a **+25 second** offset. L5 adds the offset to the pressure time to align it with the temperature source.

Temperature has one missing measurement and a rise at 380–434 s. Flow samples every two seconds, has two missing measurements, and stops at 520 s. Pressure samples irregularly, has a long interruption near 220–280 s, missing measurements, one duplicate timestamp and one invalid timestamp. The quality view identifies these from the files.

Select all three signals in the catalog, open Signal Explorer, configure the pressure reference, inspect 250–470 seconds, and save the view. For Max-Z, use temperature with baseline 0–199 s and analysis 200–599 s. Analysis, incidents and reports retain the original `temp_C` key while displaying saved names and units.
