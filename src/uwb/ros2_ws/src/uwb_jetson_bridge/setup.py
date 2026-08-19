from setuptools import find_packages, setup

package_name = "uwb_jetson_bridge"
setup(name=package_name, version="0.1.0", packages=find_packages(exclude=("test",)), data_files=[("share/ament_index/resource_index/packages", [f"resource/{package_name}"]), (f"share/{package_name}", ["package.xml"])], install_requires=[], zip_safe=True, maintainer="AI Rescue Box Team", maintainer_email="maintainer@example.com", description="Jetson-side UWB ROS 2 bridge", license="Proprietary", entry_points={"console_scripts": ["jetson_bridge = uwb_jetson_bridge.node:main"]})
