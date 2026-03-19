def make_multipliers():
    return [lambda x: x * i for i in range(5)]

fns = make_multipliers()
print([f(2) for f in fns])
