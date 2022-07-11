from setuptools import setup, find_packages

setup(
    name='ScalableTwitchIrcClient',
    version='0.2.7',
    url='https://github.com/deemonrider/scalable-twitch-irc-client.git',
    author='DeemonRider',
    author_email='',
    description='-',
    packages=find_packages(),
    install_requires=[
        "requests==2.27.1"
    ],
)