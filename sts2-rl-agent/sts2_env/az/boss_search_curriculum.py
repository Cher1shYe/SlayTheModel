"""G2.3e: unchanged deck mixture, fresh train/heldout seed namespaces."""
from dataclasses import replace
from . import boss_curriculum as previous

VERSION = "boss-search-course-v1"


def configuration():
    return dict(previous.configuration(), version=VERSION, train_master_offset=16,
                heldout_master_seeds={"validation":188,"test":286},
                initial_weights="G2.3c frozen champions; fresh optimizer")


def generate(master, iteration, job, split="train"):
    recipe=previous.generate(master+12 if split=="train" else master,iteration,job,split)
    group="focus" if job >= (90 if split=="train" else 180) else "retained"
    return replace(recipe,scenario_id=f"{VERSION}-{group}-{split}-{master}-{iteration}-{job}")


def manifest():
    return ([generate(42,0,j) for j in range(180)]
            +[generate(188,0,j,"validation") for j in range(256)]
            +[generate(286,0,j,"test") for j in range(216)])
