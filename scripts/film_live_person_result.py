#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import math
import os
import urllib.request
from pathlib import Path

from jetson_app.config import load_config
from jetson_app.domain import utc_now
from jetson_app.mission import MissionManager


API = os.environ.get(
    "AI_RESCUE_JETSON_LOCAL_API",
    "http://127.0.0.1:8001",
).rstrip("/")


def get_json(path: str):
    with urllib.request.urlopen(
        API + path,
        timeout=5,
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def distance(points):
    total = 0.0

    for first, second in zip(points, points[1:]):
        total += math.hypot(
            float(second["x"]) - float(first["x"]),
            float(second["y"]) - float(first["y"]),
        )

    return total


def main():
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
        raise SystemExit("No ACTIVE Mission")

    mission_id, mission_version = current

    live = get_json(
        "/api/v1/person-candidates/current"
    )

    candidates = [
        item
        for item in live.get("candidates", [])
        if item.get("confirmed")
        and item.get("mission_map_position") is not None
    ]

    if not candidates:
        raise SystemExit(
            "No confirmed MediaPipe person. "
            "Stand in front of Astra until observations >= 2."
        )

    # 가장 최근에 확인된 confirmed 사람을 사용
    candidates.sort(
        key=lambda item: (
            str(item.get("last_seen_at", "")),
            int(item.get("observation_count", 0)),
            float(item.get("confidence", 0.0)),
        ),
        reverse=True,
    )

    person = copy.deepcopy(candidates[0])

    mission_position = dict(
        person["mission_map_position"]
    )

    slam_position = copy.deepcopy(
        person.get("slam_map_position")
    )

    latest = manager.latest_result_version(
        mission_id,
        mission_version,
    )

    if latest is None:
        raise SystemExit(
            "No semantic_result template exists. "
            "Run scripts/film_demo_result.py first."
        )

    result = manager.load_semantic_result(
        mission_id,
        mission_version,
        latest,
    )

    new_version = latest + 1
    now = utc_now()

    # Host에 들어갈 실제 victim
    victim = {
        "detection_id": person["detection_id"],
        "tracking_id": person.get("tracking_id"),
        "class": "person",
        "rgb_bbox": copy.deepcopy(
            person.get("rgb_bbox")
        ),
        "confidence": float(
            person.get("confidence", 0.0)
        ),
        "depth_valid": bool(
            person.get("depth_valid")
        ),
        "camera_position": copy.deepcopy(
            person.get("camera_position")
        ),
        "map_position": mission_position,
        "position": mission_position,
        "detected_at": person.get(
            "detected_at",
            now,
        ),
        "last_seen_at": person.get(
            "last_seen_at",
            now,
        ),
        "source": (
            "mediapipe_object_detector"
            "+measured_depth"
            "+tf_slam_map"
        ),
        "host_status": "confirmed",
        "observation_count": int(
            person.get("observation_count", 1)
        ),
    }

    result["result_version"] = new_version
    result["artifact_version"] = new_version
    result["created_at"] = now

    result["victim_candidates"] = [victim]
    result["confirmed_victims"] = [victim]

    # scripted obstacles / risks는 그대로 유지하되,
    # route의 최종 목적지만 실제 victim 위치로 변경
    routes = list(
        copy.deepcopy(
            result.get("entry_routes", [])
        )
    )

    if routes:
        route = routes[0]

        start = route.get("start") or {
            "x": float(
                result["robot_pose"]["x"]
            ),
            "y": float(
                result["robot_pose"]["y"]
            ),
        }

        points = list(
            route.get("points", [])
        )

        if len(points) < 2:
            points = [
                dict(start),
                dict(mission_position),
            ]
        else:
            points[-1] = dict(
                mission_position
            )

        route["goal"] = dict(
            mission_position
        )
        route["points"] = points
        route["target_id"] = victim[
            "detection_id"
        ]
        route["created_at"] = now
        route["total_distance"] = distance(
            points
        )

        result["entry_routes"] = [route]

    else:
        start = {
            "x": float(
                result["robot_pose"]["x"]
            ),
            "y": float(
                result["robot_pose"]["y"]
            ),
        }

        points = [
            start,
            dict(mission_position),
        ]

        result["entry_routes"] = [
            {
                "route_id": "route-live-victim-01",
                "start": start,
                "goal": dict(mission_position),
                "points": points,
                "total_distance": distance(points),
                "risk_cost": 0.0,
                "contains_unknown": False,
                "created_at": now,
                "map_version": int(
                    result["slam_map_version"]
                ),
                "target_id": victim[
                    "detection_id"
                ],
            }
        ]

    # 영상용 scripted 환경 + 실제 AI victim임을 데이터에 명시
    result["source"] = (
        "scripted_demo_with_live_mediapipe_victim"
    )
    result["analysis_mode"] = "unknown"

    result["live_person_provenance"] = {
        "detector": "MediaPipe EfficientDet-Lite0",
        "confidence": victim["confidence"],
        "observation_count": victim[
            "observation_count"
        ],
        "depth_valid": victim[
            "depth_valid"
        ],
        "slam_map_position": slam_position,
        "mission_map_position": mission_position,
        "coordinate_conversion": (
            "T_mission_map_from_slam_map"
        ),
    }

    # 전체 confidence는 최소한 실제 person confidence 반영
    result["confidence"] = max(
        float(result.get("confidence", 0.0)),
        victim["confidence"],
    )

    path = manager.save_semantic_result(
        mission_id,
        mission_version,
        result,
    )

    print()
    print("========================================")
    print("HYBRID SEMANTIC RESULT SAVED")
    print("========================================")
    print(
        f"Mission           : "
        f"{mission_id} v{mission_version}"
    )
    print(
        f"Result version    : {new_version}"
    )
    print(
        f"Detection         : "
        f"{victim['detection_id']}"
    )
    print(
        f"Confidence        : "
        f"{victim['confidence']:.3f}"
    )
    print(
        f"Observations      : "
        f"{victim['observation_count']}"
    )
    print(
        f"SLAM map          : "
        f"{slam_position}"
    )
    print(
        f"Mission map       : "
        f"{mission_position}"
    )
    print(
        f"Saved             : {path}"
    )
    print("========================================")


if __name__ == "__main__":
    main()
