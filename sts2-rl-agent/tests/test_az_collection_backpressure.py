"""Bound pending results independently of episode count; preserve ordered jobs."""
from types import SimpleNamespace
import pytest
from sts2_env.az.self_play import Collector


class Future:
    def __init__(self,pool,value):
        self.pool,self.value=pool,value
    def result(self):
        self.pool.outstanding-=1
        if self.value==self.pool.fail:
            raise RuntimeError("injected worker failure")
        return self.value
    def cancel(self):
        self.pool.cancelled+=1


class Pool:
    def __init__(self,fail=None):
        self.outstanding=self.maximum=self.submitted=self.cancelled=0
        self.fail=fail
    def submit(self,fn,job):
        self.outstanding+=1
        self.maximum=max(self.maximum,self.outstanding)
        self.submitted+=1
        return Future(self,job.job_id)


def collector(fail=None):
    result=Collector.__new__(Collector)
    result.workers=2
    result.pool=Pool(fail)
    return result


def jobs():
    return [SimpleNamespace(master_seed=42,iteration=0,job_id=str(j)) for j in range(20)]


def test_consumer_backpressure_bounds_pending_results_and_preserves_order():
    c=collector()
    stream=c.iter_collect(jobs())
    assert next(stream)=="0"
    assert c.pool.submitted==2
    assert ["0"]+list(stream)==[str(j) for j in range(20)]
    assert c.pool.maximum==2


def test_worker_error_is_not_skipped_and_pending_jobs_are_cancelled():
    c=collector("1")
    stream=c.iter_collect(jobs())
    assert next(stream)=="0"
    with pytest.raises(RuntimeError,match="worker failure"):
        next(stream)
    assert c.pool.submitted==3
    assert c.pool.cancelled==1


def test_duplicate_jobs_rejected_before_any_submission():
    c=collector()
    batch=jobs()
    with pytest.raises(ValueError,match="Duplicate"):
        list(c.iter_collect(batch+[batch[0]]))
    assert c.pool.submitted==0
