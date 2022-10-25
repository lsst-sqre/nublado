from ..models.v1.external.userdata import UserQuota, UserQuotaQuantum


def quota_from_size(size: str) -> UserQuota:
    cpu = 1.0
    mem = 3 * (2**30)  # Replace with reading definition from config
    return UserQuota(
        requests=UserQuotaQuantum(cpu=cpu / 4, mem=int(mem / 4)),
        limits=UserQuotaQuantum(cpu=cpu, mem=mem),
    )
