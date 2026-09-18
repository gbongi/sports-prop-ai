def current_streak(values, line):
    more = 0
    less = 0
    for value in reversed(values):
        if value > line:
            more += 1
        else:
            break
    for value in reversed(values):
        if value < line:
            less += 1
        else:
            break
    return {'more': more, 'less': less}
