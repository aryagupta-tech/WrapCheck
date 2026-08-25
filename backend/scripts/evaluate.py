from time import perf_counter

from app.comparison import compare_observations
from app.fixtures import CURRENT_OBSERVATIONS, REFERENCE_OBSERVATIONS

KNOWN = {"Mara's watch", "drinking glass", "red folder", "Mara's jacket", "Mara line 18"}
started = perf_counter()
conflicts = compare_observations(REFERENCE_OBSERVATIONS, CURRENT_OBSERVATIONS)
detected = {item.entity_name for item in conflicts}
true_positives = len(KNOWN & detected)
false_positives = len(detected - KNOWN)
missed = len(KNOWN - detected)
precision = true_positives / max(1, true_positives + false_positives)
recall = true_positives / len(KNOWN)
print(f"Known mismatches: {len(KNOWN)}")
print(f"Detected mismatches: {len(detected)}")
print(f"Missed mismatches: {missed}")
print(f"False positives: {false_positives}")
print(f"Precision: {precision:.3f}")
print(f"Recall: {recall:.3f}")
print(f"Processing duration: {(perf_counter() - started) * 1000:.2f} ms")
