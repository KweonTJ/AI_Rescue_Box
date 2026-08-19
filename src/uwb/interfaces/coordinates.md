# Coordinate Contract

## Frames

| 이름 | 단위 | 소유자 | 용도 |
|---|---|---|---|
| `image_px` | pixel | Host | 원본 구조도 편집 |
| `mission_map` | meter | Contract | Host와 최종 Semantic Result의 표준 좌표 |
| `slam_map` | meter | RTAB-Map | 사고 후 Live Map |
| `camera_link` / optical frame | meter | Astra/TF | Depth 역투영 |
| `base_link` | meter | 플랫폼 | 로봇 기준 자세 |

## Transform

`T_mission_map_from_slam_map`은 2D rigid transform이다.

```text
x_mission = cos(yaw) * x_slam - sin(yaw) * y_slam + tx
y_mission = sin(yaw) * x_slam + cos(yaw) * y_slam + ty
yaw_mission = yaw_slam + yaw
```

Scale은 Host의 `meters_per_pixel`에서 결정하며 정합 단계에서 임의로 비등방 확대하지 않는다. 자동 정합 confidence가 낮으면 Host가 제공한 초기 pose를 사용한다.

## Source state

지도 셀과 Semantic 객체는 `source`, `confidence`, `state`, `last_observed_at`을 유지한다. `observed`, `prior_only`, `interpolated`, `ai_suggested`, `unknown`을 구분하며 AI 보완 값을 실제 관측으로 표시하지 않는다.
