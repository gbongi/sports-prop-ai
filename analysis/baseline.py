import statistics


def summarize(values):
    if not values:
        raise ValueError('values cannot be empty')
    return {
        'average': statistics.mean(values),
        'median': statistics.median(values),
        'std_dev': statistics.stdev(values) if len(values) > 1 else 0.0,
        'l5': statistics.mean(values[-5:]),
        'l10': statistics.mean(values[-10:]),
        'l20': statistics.mean(values[-20:]),
    }
