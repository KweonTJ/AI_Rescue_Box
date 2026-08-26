#!/usr/bin/env python3

from __future__ import annotations

import math
import os
from pathlib import Path

from jetson_app.config import load_config
from jetson_app.domain import utc_now
from jetson_app.mission import MissionManager


def point(x, y):
    return {"x": float(x), "y": float(y)}


def rectangle(cx, cy, half_x, half_y):
    return [
        point(cx - half_x, cy - half_y),
        point(cx + half_x, cy - half_y),
        point(cx + half_x, cy + half_y),
        point(cx - half_x, cy + half_y),
    ]


def distance(a, b):
    return math.hypot(
        b["x"] - a["x"],
        b["y"] - a["y"],
    )


def path_distance(points):
    return sum(
        distance(points[i], points[i + 1])
        for i in range(len(points) - 1)
    )


config = load_config()

data_root = Path(
    os.environ.get(
        "AI_RESCUE_DATA_ROOT",
        str(config.data_root),
    )
).expanduser()

manager = MissionManager(
    data_root / "missions",
    max_map_bytes=config.max_map_bytes,
    max_json_bytes=config.max_json_bytes,
)

current = manager.current_mission_ref()

if current is None:
    raise SystemExit("ACTIVE Mission이 없습니다.")

mission_id, mission_version = current
mission = manager.load_mission(mission_id, mission_version)

print(f"ACTIVE Mission: {mission_id} v{mission_version}")

if mission_id != "asdf" or mission_version != 1:
    raise SystemExit(
        f"예상 Mission은 asdf v1인데 현재는 {mission_id} v{mission_version} 입니다."
    )

entrances = mission.manifest.entrances

if len(entrances) != 3:
    raise SystemExit(
        f"촬영용 Mission은 위치 3개가 필요합니다. 현재 {len(entrances)}개"
    )

# ----------------------------------------------------------
# 사용자가 구조도에서 미리 지정한 위치
#
# entrance-1 = 사람
# entrance-2 = 장애물 1
# entrance-3 = 장애물 2
# ----------------------------------------------------------

victim = entrances[0]
obstacle_1 = entrances[1]
obstacle_2 = entrances[2]

victim_pos = point(victim.x, victim.y)
obs1_pos = point(obstacle_1.x, obstacle_1.y)
obs2_pos = point(obstacle_2.x, obstacle_2.y)

now = utc_now()

latest = manager.latest_result_version(
    mission_id,
    mission_version,
)

result_version = 1 if latest is None else latest + 1


# ----------------------------------------------------------
# 요구조자
# ----------------------------------------------------------

victim_data = {
    "detection_id": "victim-01",
    "tracking_id": "demo-track-01",
    "class": "person",

    # 카메라 bbox 형식 유지
    "rgb_bbox": {
        "x": 850.0,
        "y": 125.0,
        "width": 72.0,
        "height": 110.0,
    },

    "confidence": 0.96,

    # 촬영용 결과이므로 실제 Depth 측정값을 위조하지 않음
    "depth_valid": False,
    "camera_position": None,

    "map_position": victim_pos,
    "position": victim_pos,

    "detected_at": now,
    "last_seen_at": now,

    "source": "scripted_demo",
    "host_status": "confirmed",
    "observation_count": 3,
}


# ----------------------------------------------------------
# 장애물 실제 영역
# 약 1.5 m × 2.0 m 크기로 표시
# ----------------------------------------------------------

obstacle_1_polygon = rectangle(
    obstacle_1.x,
    obstacle_1.y,
    0.75,
    1.0,
)

obstacle_2_polygon = rectangle(
    obstacle_2.x,
    obstacle_2.y,
    0.75,
    1.0,
)


# ----------------------------------------------------------
# 위험구역
# 장애물보다 조금 넓게 잡음
# ----------------------------------------------------------

risk_1_polygon = rectangle(
    obstacle_1.x,
    obstacle_1.y,
    1.20,
    1.55,
)

risk_2_polygon = rectangle(
    obstacle_2.x,
    obstacle_2.y,
    1.20,
    1.55,
)

risk_zones = [
    {
        "risk_id": "risk-obstacle-01",
        "risk_type": "passage_obstruction",
        "polygon": risk_1_polygon,
        "center": obs1_pos,
        "severity": 0.72,
        "confidence": 0.93,
        "rationale": "corridor passage obstructed by detected obstacle",
        "source": "scripted_demo",
        "observed_at": now,
        "state": "observed",
        "host_status": "candidate",
    },
    {
        "risk_id": "risk-obstacle-02",
        "risk_type": "passage_obstruction",
        "polygon": risk_2_polygon,
        "center": obs2_pos,
        "severity": 0.68,
        "confidence": 0.91,
        "rationale": "corridor passage obstructed by detected obstacle",
        "source": "scripted_demo",
        "observed_at": now,
        "state": "observed",
        "host_status": "candidate",
    },
]


# ----------------------------------------------------------
# 로봇 탐색 궤적
#
# 중앙에서 시작
# → 왼쪽 장애물 방향 탐색
# → 다시 오른쪽으로 이동
# → 장애물 1 우회
# → 요구조자 확인
# → 시작 위치 복귀
# ----------------------------------------------------------

trajectory_xy = [
    (0.0, 0.0),

    # 왼쪽 탐색
    (1.2, -4.0),
    (2.6, -8.0),
    (3.8, -11.5),
    (4.0, -12.5),

    # 복귀 후 오른쪽 탐색
    (2.0, -5.0),
    (1.5, 0.0),
    (2.0, 4.0),

    # obstacle-1을 위쪽으로 우회
    (2.8, 8.0),
    (2.8, 12.0),

    # 요구조자 방향
    (3.5, 16.0),
    (4.6, 19.5),
    (5.5, 21.5),
    (victim.x, victim.y),

    # 로봇 복귀
    (4.5, 18.0),
    (3.0, 12.0),
    (2.0, 6.0),
    (1.0, 2.0),
    (0.0, 0.0),
]

robot_trajectory = [
    {
        "x": float(x),
        "y": float(y),
        "yaw": 0.0,
    }
    for x, y in trajectory_xy
]


# ----------------------------------------------------------
# 구조대 추천 진입 경로
#
# obstacle-1 위험구역을 피해서 요구조자로 이동
# ----------------------------------------------------------

route_points = [
    point(0.0, 0.0),
    point(1.5, 3.5),
    point(2.5, 7.0),
    point(2.7, 11.5),
    point(3.2, 15.0),
    point(4.2, 18.5),
    point(5.2, 21.0),
    victim_pos,
]

entry_route = {
    "route_id": "route-victim-01",
    "start": route_points[0],
    "goal": victim_pos,
    "points": route_points,
    "total_distance": path_distance(route_points),
    "risk_cost": 0.17,
    "contains_unknown": False,
    "created_at": now,
    "map_version": 1,
    "target_id": "victim-01",
}


# ----------------------------------------------------------
# Semantic Result
#
# 내부적으로 scripted_demo임을 명시.
# Host 화면에는 일반 결과와 같은 구조로 표시됨.
# ----------------------------------------------------------

semantic_result = {
    "schema_version": "1.0",

    "mission_id": mission_id,

    "artifact_version": result_version,
    "base_map_version": mission_version,
    "result_version": result_version,

    "slam_map_version": 1,

    "created_at": now,

    "coordinate_frame": "mission_map",
    "units": "meters",

    "source": "scripted_demo",
    "analysis_mode": "unknown",
    "confidence": 0.94,

    # 촬영 종료 시 로봇은 동방으로 복귀했다고 가정
    "robot_pose": {
        "x": 0.0,
        "y": 0.0,
        "yaw": 0.0,
    },

    "robot_trajectory": robot_trajectory,

    # Host의 후보 검토 UI에서도 사용할 수 있도록 포함
    "victim_candidates": [
        dict(victim_data),
    ],

    # 처음부터 확정 요구조자로 표시
    "confirmed_victims": [
        dict(victim_data),
    ],

    "obstacles": [
        obstacle_1_polygon,
        obstacle_2_polygon,
    ],

    "risk_zones": risk_zones,

    "entry_routes": [
        entry_route,
    ],

    # 구조 인원은 현장 분석 뒤 Host에서 판단하기로 했으므로
    # Jetson 단계에서는 추천 팀 수를 정하지 않음
    "team_recommendations": [],

    "safe_waiting_points": [],

    "explored_areas": [],
    "unknown_areas": [],

    "map_alignment": {
        "status": "aligned",
        "automatic_map_alignment": True,
        "source": "scripted_demo",
    },
}


saved = manager.save_semantic_result(
    mission_id,
    mission_version,
    semantic_result,
)

print()
print("======================================")
print("FILM DEMO RESULT CREATED")
print("======================================")
print(f"Mission       : {mission_id} v{mission_version}")
print(f"Result        : v{result_version}")
print(f"Saved         : {saved}")
print()
print(
    "Victim       : "
    f"({victim.x:.3f}, {victim.y:.3f})"
)
print(
    "Obstacle 1   : "
    f"({obstacle_1.x:.3f}, {obstacle_1.y:.3f})"
)
print(
    "Obstacle 2   : "
    f"({obstacle_2.x:.3f}, {obstacle_2.y:.3f})"
)
print(
    "Route length : "
    f"{entry_route['total_distance']:.2f} m"
)
print("======================================")
