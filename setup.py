from setuptools import setup

VERSION = "0.0.1"
NAME = "meltem-to-mqtt"

install_requires = ["minimalmodbus", "paho-mqtt", "Events"]

setup(
    name=NAME,
    version=VERSION,
    description="Mapper for Meltem data to MQTT",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Max Dhom",
    author_email="info@mdwd.org",
    license="MIT",
    url="https://github.com/mdhom/meltem-to-mqtt",
    python_requires=">=3.7",
    install_requires=install_requires,
    packages=["meltem_to_mqtt"],
    entry_points={
        "console_scripts": [
            "meltem-to-mqtt = meltem_to_mqtt.meltem_to_mqtt_base:main",
        ],
    },
)
