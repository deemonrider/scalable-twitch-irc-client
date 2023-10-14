from setuptools import setup, find_packages

setup(
    name='scalable-twitch-irc-client',
    version='0.6.1',
    url='https://github.com/deemonrider/scalable-twitch-irc-client.git',
    author='DeemonRider',
    author_email='',
    description='-',
    packages=find_packages(),
    install_requires=[
        "requests==2.31.0"
    ],
)