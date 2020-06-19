from setuptools import setup


setup(
    name='cldfbench_lapsyd',
    py_modules=['cldfbench_lapsyd'],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'cldfbench.dataset': [
            'lapsyd=cldfbench_lapsyd:Dataset',
        ]
    },
    install_requires=[
        'cldfbench',
    ],
    extras_require={
        'test': [
            'pytest-cldf',
        ],
    },
)
