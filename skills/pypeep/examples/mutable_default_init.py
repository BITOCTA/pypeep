class Node:
    def __init__(self, value, children=[]):
        self.value = value
        self.children = children

a = Node(1)
b = Node(2)
a.children.append(b)

print(b.children)
print(a.children is b.children)
