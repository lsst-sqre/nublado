import aiojobs


class AIOJobDependency:
    """Provides an ``aiojobs.Scheduler`` dependency for fire-and-forget
    job management.
    """

    async def __call__(self) -> aiojobs.Scheduler:
        return aiojobs.Scheduler()


scheduler_dependency = AIOJobDependency()
"""The dependency that returns the job scheduler."""
