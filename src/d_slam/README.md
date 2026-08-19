# d_slam

Jetson sensor, SLAM, AI analysis, API and UI ownership.

- `astra_camera/`, `astra_camera_msgs/`: Astra RGB-D source
- `d_slam/`: existing SLAM/nvblox/RTAB-Map integration
- `jetson_app/`: mission storage, sensor adapters, perception, depth fusion, risk, alignment, planning, semantic result and FastAPI
- `flutter_app/`: Jetson operator UI

Stage 0·1 only relocates sources. It does not wire received Mission artifacts into RTAB-Map or run a Host↔UWB↔Jetson mission flow.
