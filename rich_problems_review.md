# MathForge — 30 rich (max-thinking) problems

## 1. [Algebra]  answer = 900   (PE 4.3 / SE 4.2, difficulty 5.5)

A sequence of positive integers $a_1, a_2, a_3, \dots$ satisfies
$$a_{n+1}\,a_{n-1} = a_n + 1 \qquad \text{for every integer } n \ge 2.$$
Find $\displaystyle\sum_{n=1}^{500} a_n$.

*Crux:* The Lyness recurrence $a_{n+1}=\frac{a_n+1}{a_{n-1}}$ is periodic with period $5$ for all positive reals, and the only positive‑integer cycle is a shift of $(1,1,2,3,2)$, whose block sum is $9$.

<details><summary>solution</summary>

**Step 1: The sequence has period 5.**

For $n\ge 2$ the relation gives $a_{n+1}=\dfrac{a_n+1}{a_{n-1}}$. Write $a_1=a,\ a_2=b$ (both positive). Then
$$a_3=\frac{b+1}{a},\qquad a_4=\frac{a_3+1}{b}=\frac{\frac{b+1}{a}+1}{b}=\frac{a+b+1}{ab}.$$
Next,
$$a_5=\frac{a_4+1}{a_3}=\frac{\frac{a+b+1}{ab}+1}{\frac{b+1}{a}}=\frac{a+b+1+ab}{b(b+1)}=\frac{(a+1)(b+1)}{b(b+1)}=\frac{a+1}{b},$$
using $a+b+1+ab=(a+1)(b+1)$. Continuing,
$$a_6=\frac{a_5+1}{a_4}=\frac{\frac{a+1}{b}+1}{\frac{a+b+1}{ab}}=\frac{a+b+1}{b}\cdot\frac{ab}{a+b+1}=a=a_1,$$
$$a_7=\frac{a_6+1}{a_5}=\frac{a+1}{\frac{a+1}{b}}=b=a_2.$$
Hence $a_{n+5}=a_n$ for all $n$: **every** solution is periodic with period $5$.

**Step 2: The minimum term equals 1.**

Since the sequence is a $5$-cycle of positive integers, let $m$ be its minimum value, attained at some index $i$. From the recurrence,
$$a_{i+1}=\frac{a_i+1}{a_{i-1}}=\frac{m+1}{a_{i-1}}\le\frac{m+1}{m}=1+\frac1m,$$
because $a_{i-1}\ge m$. If $m\ge 2$, then $a_{i+1}\le \tfrac32<2$, forcing $a_{i+1}=1<m$, contradicting minimality. Therefore $m=1$: some term equals $1$.

**Step 3: Classify all integer cycles.**

Shift indices so that $a_1=1$. Reading the recurrence at $n=1$ (indices mod $5$, so $a_0=a_5$):
$$a_2\,a_5=a_1+1=2.$$
Thus $\{a_2,a_5\}=\{1,2\}$.

- If $a_2=1,\ a_5=2$: then $a_3=\frac{a_2+1}{a_1}=2$, and $n=3$ gives $a_4 a_2=a_3+1=3\Rightarrow a_4=3$. Checks: $n=4:\ a_5 a_3=4=a_4+1$ ✓; $n=5:\ a_1 a_4=3=a_5+1$ ✓. Cycle $(1,1,2,3,2)$.
- If $a_2=2,\ a_5=1$: then $a_3=3$, and $n=3$ gives $a_4a_2=4\Rightarrow a_4=2$. Checks: $n=4:\ a_5a_3=3=a_4+1$ ✓; $n=5:\ a_1a_4=2=a_5+1$ ✓. Cycle $(1,2,3,2,1)$.

Both are cyclic shifts of the same multiset $\{1,1,2,3,2\}$. Hence **every** positive-integer solution is a shift of $(1,1,2,3,2)$.

**Step 4: Compute the sum.**

The sum over one full period is
$$1+1+2+3+2=9,$$
and this is independent of the phase (starting point) of the cycle. Since $500=5\cdot 100$ is an exact number of periods,
$$\sum_{n=1}^{500} a_n = 100\cdot 9 = \boxed{900}.$$

This value is the same for every admissible sequence, so it is well-defined.
</details>

---

## 2. [Algebra]  answer = 19   (PE 3.6 / SE 4.2, difficulty 5.5)

Let $f$ be a real-valued function defined for all real $x$ with $x \notin \{0,1\}$, satisfying
$$f(x) + f\!\left(\frac{x-1}{x}\right) = 8x^2$$
for every $x$ in its domain. Given that this condition determines $f$ uniquely, find $f(2)$.

*Crux:* The substitution map $g(x)=\dfrac{x-1}{x}=1-\tfrac1x$ has order $3$ (i.e. $g(g(g(x)))=x$), so three iterations of the equation form a solvable $3\times3$ linear system for $f$ on each orbit.

<details><summary>solution</summary>

Let $g(x) = \dfrac{x-1}{x}$. We compute its iterates:
$$g(g(x)) = \frac{g(x)-1}{g(x)} = \frac{\frac{x-1}{x}-1}{\frac{x-1}{x}} = \frac{\frac{-1}{x}}{\frac{x-1}{x}} = \frac{-1}{x-1} = \frac{1}{1-x},$$
$$g(g(g(x))) = \frac{\frac{1}{1-x}-1}{\frac{1}{1-x}} = \frac{\frac{1-(1-x)}{1-x}}{\frac{1}{1-x}} = \frac{x}{1-x}\cdot(1-x) = x.$$
So $g$ has order $3$: applying it three times returns $x$. (One checks $g$ maps $\mathbb{R}\setminus\{0,1\}$ into itself, since $g(x)=0$ only at $x=1$ and $g(x)=1$ is impossible, so every orbit is a genuine $3$-cycle.)

Take the orbit of $x=2$:
$$g(2) = \frac{2-1}{2} = \frac12, \qquad g\!\left(\tfrac12\right) = \frac{\frac12-1}{\frac12} = -1, \qquad g(-1) = \frac{-1-1}{-1} = 2.$$
So the orbit is $\{2,\ \tfrac12,\ -1\}$.

Write the given equation at these three points (using $8x^2$ on the right):
$$
\begin{aligned}
f(2) + f\!\left(\tfrac12\right) &= 8\cdot 2^2 = 32,\\
f\!\left(\tfrac12\right) + f(-1) &= 8\cdot \left(\tfrac12\right)^2 = 2,\\
f(-1) + f(2) &= 8\cdot(-1)^2 = 8.
\end{aligned}
$$

Add all three: $2\big(f(2)+f(\tfrac12)+f(-1)\big) = 32 + 2 + 8 = 42$, so
$$f(2)+f\!\left(\tfrac12\right)+f(-1) = 21.$$
Subtract the second equation $f(\tfrac12)+f(-1)=2$:
$$f(2) = 21 - 2 = 19.$$

**Verification.** From the equations, $f(\tfrac12)=32-19=13$ and $f(-1)=8-19=-11$. Then:
- $f(2)+f(\tfrac12)=19+13=32=8\cdot2^2$ ✓
- $f(\tfrac12)+f(-1)=13-11=2=8\cdot(\tfrac12)^2$ ✓
- $f(-1)+f(2)=-11+19=8=8\cdot(-1)^2$ ✓

All conditions hold, and the $3\times3$ system has determinant $2\neq0$, so the solution is unique. Hence
$$f(2) = \boxed{19}.$$
</details>

---

## 3. [Combinatorics]  answer = 125   (PE 4.6 / SE 4.7, difficulty 5.5)

There is a one-way circular road with $5$ parking spots, labeled $0,1,2,3,4$ in clockwise order. Four cars, numbered $1,2,3,4$, arrive one at a time in that order. Car $i$ has a favorite spot $f_i \in \{0,1,2,3,4\}$. When car $i$ arrives it drives directly to spot $f_i$; if that spot is empty it parks there, and otherwise it continues clockwise (visiting spots in the cyclic order $\ldots \to j \to j+1 \to \cdots \to 4 \to 0 \to \cdots$) and parks in the first empty spot it encounters.

Because there are $5$ spots and only $4$ cars, every car always parks, and exactly one spot is left empty after all four cars have parked.

Determine the number of preference sequences $(f_1,f_2,f_3,f_4)$ for which the spot left empty is spot $0$.

*Crux:* Rotational symmetry of the circular parking process makes each of the 5 spots equally likely to be the empty one, so the count is simply $5^4/5$.

<details><summary>solution</summary>

Let $\mathcal{S}$ be the set of all $5^4 = 625$ preference sequences $(f_1,f_2,f_3,f_4)$ with each $f_i \in \{0,1,2,3,4\}$. Since there are $5$ spots and $4$ cars, each car's clockwise search always finds an empty spot, so every car parks and precisely one spot remains empty. Thus each sequence $F \in \mathcal{S}$ determines a well-defined "empty spot" $E(F) \in \{0,1,2,3,4\}$.

Partition $\mathcal{S}$ into five classes $A_s = \{F : E(F) = s\}$ for $s = 0,1,2,3,4$. We claim all five classes have the same size.

Consider the rotation map
$$\phi(f_1,f_2,f_3,f_4) = \big((f_1{+}1)\bmod 5,\ (f_2{+}1)\bmod 5,\ (f_3{+}1)\bmod 5,\ (f_4{+}1)\bmod 5\big).$$
This is a bijection from $\mathcal{S}$ to itself (it is invertible by subtracting $1$).

Key observation (rotational equivariance): the entire parking process lives on a circle whose dynamics are unchanged if we rotate everything by one spot. Concretely, run the process for $F$ and separately for $\phi(F)$. At every stage, car $i$ under $\phi(F)$ starts one spot clockwise of where it started under $F$, and encounters exactly the "rotated by $+1$" configuration of occupied spots. Hence car $i$ parks exactly one spot clockwise (mod $5$) of where it parked under $F$. Therefore the final set of occupied spots for $\phi(F)$ is the $+1$ rotation of that for $F$, and consequently
$$E(\phi(F)) = (E(F)+1) \bmod 5.$$

Thus $\phi$ maps $A_s$ bijectively onto $A_{(s+1)\bmod 5}$. It follows that
$$|A_0| = |A_1| = |A_2| = |A_3| = |A_4|,$$
and since these five sets partition $\mathcal{S}$,
$$|A_0| = \frac{5^4}{5} = \frac{625}{5} = 125.$$

(As a check on the mechanism, consider $2$ cars on $3$ spots $\{0,1,2\}$: symmetry predicts $3^2/3 = 3$ sequences leaving spot $0$ empty. Direct enumeration of all $9$ sequences gives exactly $(1,1),(1,2),(2,1)$ leaving spot $0$ empty — indeed $3$, confirming the argument.)

Therefore the number of preference sequences leaving spot $0$ empty is $\boxed{125}$.
</details>

---

## 4. [Combinatorics]  answer = 950   (PE 4.3 / SE 4.5, difficulty 5.5)

For a positive integer $n$, a **partition into distinct parts** is a way of writing $n$ as a sum of distinct positive integers, where order does not matter (for example, $6 = 6 = 1+5 = 2+4 = 1+2+3$).

Let $E(n)$ be the number of partitions of $n$ into distinct parts using an **even** number of parts, and let $O(n)$ be the number using an **odd** number of parts. (For $n=6$: the partitions $1+5,\,2+4$ have $2$ parts and $6,\,1+2+3$ have $1$ and $3$ parts, so $E(6)=2$ and $O(6)=2$.)

Determine the number of integers $n$ with $1 \le n \le 1000$ for which
$$E(n) = O(n).$$

*Crux:* The signed count $E(n)-O(n)$ is the coefficient of $x^n$ in $\prod_{k\ge1}(1-x^k)$, which by Euler's Pentagonal Number Theorem (Franklin's sign-reversing involution) is $0$ except at generalized pentagonal numbers.

<details><summary>solution</summary>

**Setting up a signed generating function.**
Consider building a partition into distinct parts by deciding, for each integer $k\ge 1$, whether $k$ is used (once) or not. Weight each partition by $(-1)^{(\text{number of parts})}$. A part $k$ contributes the factor $\bigl(1 + (-1)\,x^{k}\bigr) = (1 - x^k)$: either it is absent (contributing $1$) or present, contributing one factor of $x^k$ and one sign $-1$. Hence
$$
\sum_{n\ge 0}\bigl(E(n)-O(n)\bigr)x^n \;=\; \prod_{k\ge 1}\bigl(1 - x^k\bigr).
$$

**Franklin's involution / Euler's Pentagonal Number Theorem.**
Take any partition $\lambda$ of $n$ into distinct parts. Let $s$ be its smallest part, and let $t$ be the number of parts in the maximal "staircase" of consecutive integers containing the largest part (i.e. the largest part $M$, then $M-1$ if present, etc.). Franklin's map either removes the smallest row and appends $1$ to each of the top $s$ rows, or removes the staircase of size $t$ and creates a new smallest row of size $t$; exactly one operation is legal and keeps the parts distinct, and it always changes the parity of the number of parts. This is a sign-reversing involution, so it cancels partitions in pairs — **except** when the smallest row and the top staircase overlap. Those exceptional (fixed) cases occur precisely when
$$
n = \frac{j(3j-1)}{2},\qquad j\in\mathbb{Z},
$$
the **generalized pentagonal numbers**, and each such $n$ contributes $(-1)^{j}$. Therefore
$$
\prod_{k\ge 1}(1-x^k) = \sum_{j=-\infty}^{\infty} (-1)^{j}\,x^{\,j(3j-1)/2}.
$$

Consequently
$$
E(n)-O(n) =
\begin{cases}
(-1)^{j}, & n=\tfrac{j(3j-1)}{2}\text{ for some integer }j,\\[4pt]
0, & \text{otherwise.}
\end{cases}
$$

So $E(n)=O(n)$ **iff $n$ is not a generalized pentagonal number.**

**Counting generalized pentagonal numbers in $[1,1000]$.**
Writing $j>0$ and $j<0$ separately gives two families:
$$
\frac{k(3k-1)}{2}:\ 1,5,12,22,35,\ldots \qquad
\frac{k(3k+1)}{2}:\ 2,7,15,26,40,\ldots \quad (k=1,2,3,\ldots)
$$

- For $\frac{k(3k-1)}{2}\le 1000$: $k=25$ gives $\frac{25\cdot 74}{2}=925\le 1000$, while $k=26$ gives $\frac{26\cdot 77}{2}=1001>1000$. So $k=1,\dots,25$: **25 values.**
- For $\frac{k(3k+1)}{2}\le 1000$: $k=25$ gives $\frac{25\cdot 76}{2}=950\le 1000$, while $k=26$ gives $\frac{26\cdot 79}{2}=1027>1000$. So $k=1,\dots,25$: **25 values.**

The two families are disjoint (they are distinct positive integers), giving $25+25 = 50$ generalized pentagonal numbers in $[1,1000]$.

**Double-check by listing.** Merged in increasing order:
$1,2,5,7,12,15,22,26,35,40,51,57,70,77,92,100,117,126,145,155,176,187,210,222,247,260,287,301,330,345,376,392,425,442,477,495,532,551,590,610,651,672,715,737,782,805,852,876,925,950,\;1001,\ldots$
Counting the entries up to $950$ yields exactly $50$, and the next term $1001$ exceeds $1000$. ✓

**Final count.** Among the $1000$ integers $1,\dots,1000$, exactly $50$ are generalized pentagonal (where $E\ne O$), so the number with $E(n)=O(n)$ is
$$
1000 - 50 = \boxed{950}.
$$
</details>

---

## 5. [Combinatorics]  answer = 429   (PE 4.3 / SE 4.2, difficulty 6.0)

Consider lattice paths in the plane that begin at $(0,0)$, end at $(14,0)$, and consist of $14$ steps, each either an **up** step $(1,1)$ or a **down** step $(1,-1)$. (Every such path therefore uses exactly $7$ up steps and $7$ down steps.)

Call a step of a path **below the $x$-axis** if the open segment representing that step lies strictly below the $x$-axis (touching the axis, if at all, only at an endpoint).

Among all such paths, how many have **exactly $6$ steps below the $x$-axis**?

*Crux:* Chung–Feller phenomenon: among all $\pm1$ paths from $(0,0)$ to $(2n,0)$, the number having exactly $2k$ steps below the axis equals the Catalan number $C_n$ for *every* admissible $k$, independent of $k$.

<details><summary>solution</summary>

Let $a_{n,k}$ denote the number of $\pm1$ paths from $(0,0)$ to $(2n,0)$ (using $n$ up and $n$ down steps) that have exactly $2k$ steps below the $x$-axis. Note the number of below-steps is always even, since the path only goes below the axis in maximal excursions ("arches") of even length. We must find $a_{7,3}$ (here $2k=6\Rightarrow k=3$).

**First-return decomposition.** Track the first time $x=2m$ where the path returns to the $x$-axis. The initial arch (of semilength $m$) either lies entirely above the axis, contributing $0$ below-steps, or entirely below, contributing $2m$ below-steps. Deleting the first and last steps of this arch leaves a Dyck-type path of length $2m-2$ that stays on one side, and there are $C_{m-1}$ of these. Hence
$$
a_{n,k}=\sum_{m=1}^{n} C_{m-1}\bigl(a_{n-m,\,k}+a_{n-m,\,k-m}\bigr),
$$
with $a_{0,0}=1$ and $a_{n,k}=0$ unless $0\le k\le n$.

**Claim:** $a_{n,k}=C_n$ for all $0\le k\le n$.

*Induction on $n$.* Base $n=0$ is clear. Assume it holds for all smaller indices. For fixed $k\in[0,n]$,
$$
a_{n,k}=\sum_{m=1}^{n}C_{m-1}\bigl(a_{n-m,k}+a_{n-m,k-m}\bigr).
$$
By hypothesis $a_{n-m,k}=C_{n-m}$ exactly when $0\le k\le n-m$, i.e. $m\le n-k$; and $a_{n-m,k-m}=C_{n-m}$ exactly when $0\le k-m\le n-m$, i.e. $m\le k$ (the upper bound is automatic as $k\le n$). Thus, writing $T(j)=\sum_{m=1}^{j}C_{m-1}C_{n-m}$,
$$
a_{n,k}=\sum_{m=1}^{n-k}C_{m-1}C_{n-m}+\sum_{m=1}^{k}C_{m-1}C_{n-m}=T(n-k)+T(k).
$$
Now use the palindromic symmetry of the summand. Substituting $m'=n+1-m$,
$$
T(n)-T(k)=\sum_{m=k+1}^{n}C_{m-1}C_{n-m}=\sum_{m'=1}^{n-k}C_{n-m'}C_{m'-1}=T(n-k).
$$
Hence $T(n-k)+T(k)=T(n)$. Finally, by the Catalan recursion,
$$
T(n)=\sum_{m=1}^{n}C_{m-1}C_{n-m}=C_n.
$$
Therefore $a_{n,k}=C_n$, completing the induction. $\qquad\blacksquare$

**Conclusion.** With $n=7$ and $k=3$,
$$
a_{7,3}=C_7=429.
$$

**Independent check.** Summing over all admissible $k=0,1,\dots,7$ gives $\sum_{k=0}^{7}a_{7,k}=8\cdot C_7=8\cdot429=3432=\binom{14}{7}$, which is the total number of paths — consistent. (A direct small-case verification for $n=2$ gives $a_{2,0}=a_{2,1}=a_{2,2}=2=C_2$, confirming the uniform distribution.)

The answer is $\boxed{429}$.
</details>

---

## 6. [Combinatorics]  answer = 324   (PE 4.2 / SE 4.3, difficulty 5.5)

The integers $1,2,\dots,12$ are placed around a circle in their natural order, so that each integer is adjacent to the two integers immediately before and after it, and $12$ is adjacent to $1$.

Call a permutation $\pi$ of $\{1,2,\dots,12\}$ **gentle** if for every $i$, the value $\pi(i)$ is either $i$ itself or one of the two integers adjacent to $i$ on the circle. (In other words, $\pi(i)-i \equiv -1,\,0,\text{ or }1 \pmod{12}$.)

Find the number of gentle permutations.

*Crux:* A permutation moving every element by at most one step around a circle is either a product of disjoint adjacent transpositions (matchings of the cycle $C_n$, counted by the Lucas number $L_n$) or one of the two full rotations, giving $L_n+2$.

<details><summary>solution</summary>

Regard the positions $1,\dots,12$ as the vertices of the cycle graph $C_{12}$; a gentle permutation sends each $i$ to itself or a neighbor, i.e. $\pi(i)\in\{i-1,i,i+1\}$ (indices mod $12$).

**Classifying gentle permutations.**
Say $i$ is an *advance* if $\pi(i)=i+1$, a *retreat* if $\pi(i)=i-1$, and a *stay* if $\pi(i)=i$.

Suppose some $i$ is an advance, so $\pi(i)=i+1$. Then vertex $i+1$ already receives its image from $i$. Consider $\pi(i+1)$:
- $\pi(i+1)=i+1$ is impossible, since $i+1$ would then be the image of both $i$ and $i+1$.
- $\pi(i+1)=i$ gives the transposition $(i\;\,i+1)$: a $2$-cycle of adjacent elements.
- $\pi(i+1)=i+2$ continues the advance.

Thus an advance either immediately closes into an adjacent transposition, or propagates $i\to i+1\to i+2\to\cdots$. On a single cycle this propagation can only close by wrapping all the way around, producing the full rotation $\pi(i)=i+1$ for all $i$. The same holds for retreats (giving $\pi(i)=i-1$ for all $i$).

Hence every gentle permutation is exactly one of:

**Case B (rotations):** the $+1$ rotation or the $-1$ rotation — exactly $2$ permutations (distinct, since $12\ge 3$).

**Case A (involutions):** a product of *disjoint adjacent transpositions*, with all other points fixed. Each such permutation corresponds bijectively to a **matching** (a set of pairwise non-adjacent edges, possibly empty) of the cycle $C_{12}$: each transposition is an edge, and fixed points are uncovered vertices.

**Counting matchings of $C_{12}$.**
Let $m(G)$ denote the number of matchings (including the empty one) of a graph $G$. For a path $P_n$, $m(P_n)=F_{n+1}$ (Fibonacci, $F_1=F_2=1$). For the cycle $C_n$, split on whether the edge $\{n,1\}$ is used:
$$m(C_n)=m(P_n)+m(P_{n-2})=F_{n+1}+F_{n-1}=L_n,$$
the Lucas number. For $n=12$:
$$m(C_{12})=F_{13}+F_{11}=233+89=322=L_{12}.$$

**Total.**
$$\#\{\text{gentle}\}=L_{12}+2=322+2=\boxed{324}.$$

**Independent check of $L_{12}$.** Lucas numbers $L_1,\dots,L_{12}=1,3,4,7,11,18,29,47,76,123,199,322$, using $L_n=L_{n-1}+L_{n-2}$; indeed $199+123=322$. Also the empty matching gives the identity, single edges give the $12$ adjacent swaps, etc., all consistent. Adding the two rotations yields $324$, which lies in $[0,999]$.
</details>

---

## 7. [Combinatorics]  answer = 486   (PE 4.2 / SE 4.3, difficulty 6.0)

A grasshopper starts at position $0$ on the integer number line. Each minute it makes one jump, moving either one unit to the left or one unit to the right. At all times its position must remain in the set $\{-2,-1,0,1,2\}$ (if the grasshopper is at $2$ it must jump left, and if it is at $-2$ it must jump right). After exactly $12$ jumps the grasshopper is once again at position $0$.

How many different sequences of $12$ jumps are possible?

*Crux:* A ±1 walk confined to the five sites $\{-2,\dots,2\}$ returning to $0$ in $2n\ge 4$ steps: its transfer matrix (path graph $P_5$) has eigenvalues $\pm\sqrt3,\pm1,0$, collapsing the count to $2\cdot 3^{\,n-1}$.

<details><summary>solution</summary>

Track how many valid partial paths end at each position after each jump. By left–right symmetry the counts at positions $p$ and $-p$ are always equal. Write the state after $t$ jumps as the vector
$$(n_{-2},\,n_{-1},\,n_0,\,n_1,\,n_2).$$
A jump sends the count at each site to its neighbors (with $-2$ and $2$ forced inward).

Start: after $0$ jumps the grasshopper is at $0$: $(0,0,1,0,0)$.

Apply the transition step by step (a site's new count is the sum of the counts of its neighbors):

- After 1: $(0,1,0,1,0)$
- After 2: $(1,0,2,0,1)$
- After 3: $(0,3,0,3,0)$
- After 4: $(3,0,6,0,3)$
- After 5: $(0,9,0,9,0)$
- After 6: $(9,0,18,0,9)$
- After 7: $(0,27,0,27,0)$
- After 8: $(27,0,54,0,27)$
- After 9: $(0,81,0,81,0)$
- After 10: $(81,0,162,0,81)$
- After 11: $(0,243,0,243,0)$
- After 12: $(243,0,486,0,243)$

The number of length‑$12$ walks returning to $0$ is the center entry after $12$ jumps: $\boxed{486}$.

**Why it collapses (the crux).** Once $t\ge 4$ the band is "saturated," and the return counts to $0$ at even times form the sequence $1,2,6,18,54,162,486$ (times $0,2,4,\dots,12$); from step $4$ onward each value is exactly $3$ times the previous. Hence for a walk of length $2n\ge4$ the count is $2\cdot 3^{\,n-1}$; with $2n=12$, $n=6$, this gives $2\cdot 3^{5}=486$.

**Independent check via eigenvalues.** The allowed sites form the path graph $P_5$, whose adjacency (transfer) matrix has eigenvalues $2\cos\frac{k\pi}{6}=\sqrt3,\,1,\,0,\,-1,\,-\sqrt3$ for $k=1,\dots,5$, with normalized eigenvector components at the center site squared equal to $\tfrac13,0,\tfrac13,0,\tfrac13$. The number of closed walks of length $12$ from the center is
$$\sum_k \frac{v_k(\text{center})^2}{1}\lambda_k^{12}=\tfrac13\big((\sqrt3)^{12}+0+0^{12}+0+(-\sqrt3)^{12}\big)=\tfrac13(729+729)=486.$$

Both methods agree: the answer is $486$.
</details>

---

## 8. [Combinatorics]  answer = 273   (PE 4.1 / SE 4.4, difficulty 6.0)

A counter begins at $0$. It then undergoes $16$ operations performed one after another; each operation is either a $+1$ (add $1$ to the counter) or a $-2$ (subtract $2$ from the counter). Among the $16$ operations, exactly $11$ are $+1$'s and exactly $5$ are $-2$'s.

Considering all $\binom{16}{5}$ possible orders in which these operations can be arranged, determine how many of these orders keep the counter's value **strictly positive** immediately after each of the $16$ operations.

*Crux:* Reading each arrangement cyclically, exactly one of its $16$ rotations keeps all partial sums positive (the Cycle Lemma for step-values $\le 1$ with total sum $1$), so the answer is $\binom{16}{5}/16$.

<details><summary>solution</summary>

Encode an ordering as a sequence $a_0,a_1,\dots,a_{15}$ where each $a_i\in\{+1,-2\}$, with eleven $+1$'s and five $-2$'s. The total of all operations is $11\cdot 1+5\cdot(-2)=1$. An ordering is **good** if all $16$ running totals are strictly positive.

**Step 1: Group arrangements into rotation classes of size 16.**
Two arrangements are equivalent if one is a cyclic rotation of the other. An arrangement fixed by a nontrivial rotation would have some period $g=\gcd(d,16)<16$, forcing $16/g\in\{2,4,8,16\}$ to divide the number of $-2$'s. But the number of $-2$'s is $5$, which is odd, so no nontrivial rotation fixes any arrangement. Hence every rotation class has exactly $16$ distinct members, and there are $\binom{16}{5}/16$ classes.

**Step 2: In each rotation class, exactly one starting point is good.**
Fix a circular arrangement $a_0,\dots,a_{15}$ (indices mod $16$), sum $=1$. Set $S_0=0$, $S_j=a_0+\cdots+a_{j-1}$ for $j=1,\dots,16$ (so $S_{16}=1$), and extend by $S_{j+16}=S_j+1$.

Starting at index $t\in\{0,\dots,15\}$ (reading $a_t,a_{t+1},\dots,a_{t+15}$) is good iff $S_m>S_t$ for all $m=t+1,\dots,t+16$. Since $S_{m+16}=S_m+1>S_m$, this window condition is equivalent to
$$S_t<S_m\quad\text{for all integers }m>t.$$
(Indeed, if it holds on $(t,t+16]$, then for $m$ in the next block $S_m=S_{m-16}+1>S_t+1>S_t$, and so on inductively.)

Let $M=\min_{0\le j\le 15}S_j$, and let $t^\*$ be the **largest** index in $\{0,\dots,15\}$ with $S_{t^\*}=M$.

*$t^\*$ is good:* For $t^\*<m\le 15$, minimality and "last occurrence" give $S_m>M=S_{t^\*}$. For $m\ge 16$, writing $m=16q+r$ with $q\ge 1$, $S_m=S_r+q\ge M+1>S_{t^\*}$.

*Uniqueness:* Suppose $t\ne t^\*$ is good.
- If $t<t^\*$: taking $m=t^\*$ requires $S_{t^\*}>S_t$, i.e. $M>S_t$, impossible.
- If $t>t^\*$: taking $m=t^\*+16$ requires $S_t<S_{t^\*+16}=M+1$, so $S_t\le M$, hence $S_t=M$ with $t>t^\*$ — contradicting that $t^\*$ is the last index attaining $M$.

Thus each rotation class contains **exactly one** good arrangement.

**Step 3: Count.**
Number of good orderings $=$ number of rotation classes $=\dfrac{1}{16}\binom{16}{5}=\dfrac{4368}{16}=273.$

**Verification (independent computation).** A good ordering is equivalent to placing the five $-2$'s at positions $p_1<\cdots<p_5$ so that after $i$ operations the count $d_i$ of $-2$'s satisfies $i-3d_i\ge 1$, i.e. the $j$-th $-2$ sits at $p_j\ge 3j+1$. This is a Łukasiewicz-path count equal to the Fuss–Catalan number
$$\frac{1}{2\cdot 5+1}\binom{3\cdot 5}{5}=\frac{1}{11}\binom{15}{5}=\frac{3003}{11}=273,$$
matching the rotation count (both equal $\frac{(3b)!}{b!(2b+1)!}$ for $b=5$). The tiny cases $b=2$ (gives $3$) and $b=3$ (gives $12$) can be checked by direct enumeration, confirming the method.

Therefore the answer is $\boxed{273}$.
</details>

---

## 9. [Combinatorics]  answer = 945   (PE 4.1 / SE 4.3, difficulty 5.5)

Let $S(n)$ denote the sum of the decimal (base $10$) digits of a nonnegative integer $n$; for example $S(145)=1+4+5=10$.

Find the number of ordered triples $(a,b,c)$ of nonnegative integers satisfying
$$a+b+c = 145 \qquad\text{and}\qquad S(a)+S(b)+S(c) = S(145).$$

*Crux:* The digit-sum condition $S(a)+S(b)+S(c)=S(a+b+c)$ holds exactly when the column addition $a+b+c$ produces no carries, which makes the digit positions independent and reduces the count to a product of $\binom{d+2}{2}$ over the digits $d$ of $145$.

<details><summary>solution</summary>

**Key identity.** For any nonnegative integers added by the usual column method, let the total number of carries be $C$. Working column by column, if $\sigma_j$ is the sum of the digits in column $j$ plus the carry into that column, then the output digit is $\sigma_j \bmod 10$ and the carry out is $\lfloor \sigma_j/10\rfloor$. Summing,
$$\sum_j \sigma_j = \big(S(a)+S(b)+S(c)\big) + \sum_j (\text{carry out of column } j),$$
and the digit sum of the result is
$$S(a+b+c)=\sum_j(\sigma_j - 10\lfloor\sigma_j/10\rfloor) = \sum_j\sigma_j - 10C = S(a)+S(b)+S(c) - 9C.$$
Hence
$$S(a)+S(b)+S(c) = S(a+b+c) \iff C = 0,$$
i.e. the condition holds **iff adding $a,b,c$ produces no carries in any column.**

**Reduction to digits.** Since $S(a+b+c)=S(145)$ is given and $a+b+c=145$, the equation forces $C=0$: no carries occur. With no carries, the digits in each column simply add to the corresponding digit of $145$. Thus the choices in different columns are completely independent:

- Units column: choose units digits $x,y,z\in\{0,\dots,9\}$ with $x+y+z = 5$.
- Tens column: choose $x,y,z$ with $x+y+z = 4$.
- Hundreds column: choose $x,y,z$ with $x+y+z = 1$.
- All higher columns: digit of $145$ is $0$, forcing all three digits to be $0$ (one way).

Because each target digit is at most $9$, the constraint "each part $\le 9$" is automatic, so the number of ordered solutions of $x+y+z=d$ is $\binom{d+2}{2}$.

**Count.** The three columns give
$$\binom{5+2}{2}\binom{4+2}{2}\binom{1+2}{2} = \binom{7}{2}\binom{6}{2}\binom{3}{2} = 21\cdot 15\cdot 3.$$

**Double-check the arithmetic (recomputed a different way).** 
$21\cdot 3 = 63$, then $63\cdot 15 = 945$. Also $15\cdot 3 = 45$, then $45\cdot 21 = 945$. Both give the same value.

**Sanity check of the method** on the small case $N=11$ (digits $1,1$): the formula predicts $\binom{3}{2}\binom{3}{2}=9$, and indeed the carry-free triples are exactly the $3\times 3 = 9$ ways to place the $1$ (units) among $a,b,c$ and the $10$ (tens) among $a,b,c$, e.g. $(11,0,0),(1,10,0),(0,1,10),\dots$, confirming the reasoning.

Therefore the number of triples is $\boxed{945}$.
</details>

---

## 10. [Combinatorics]  answer = 255   (PE 4.0 / SE 4.3, difficulty 5.5)

Consider the set of twelve positive integers
$$A=\{6,\;8,\;10,\;12,\;15,\;18,\;20,\;21,\;28,\;45,\;50,\;98\}.$$
Call a subset $T\subseteq A$ *square* if the product of all the elements of $T$ is a perfect square. (The empty product $1$ counts as a perfect square.)

How many **nonempty** square subsets does $A$ have?

*Crux:* A product of integers is a perfect square iff the sum of their squarefree-part vectors over $\mathbb{F}_2$ (indexed by primes) is zero, so the count of square subsets is $2^{\,n-r}$ where $r$ is the $\mathbb{F}_2$-rank of those vectors.

<details><summary>solution</summary>

Every positive integer $m$ can be written uniquely as $m=s\cdot k^2$ where $s$ is squarefree. The product of a set of integers is a perfect square if and only if each prime occurs to an even total exponent, i.e. if and only if the *squarefree parts* combine to a perfect square. 

Encode each integer by a vector over $\mathbb{F}_2$ whose coordinates are the parities of the exponents of the primes appearing in $A$. The only primes dividing elements of $A$ are $2,3,5,7$, so each element maps to a vector in $\mathbb{F}_2^4$ (coordinates in the order $2,3,5,7$):

$$
\begin{array}{llll}
6=2\cdot3 &\to (1,1,0,0) & 20=2^2\cdot5 &\to (0,0,1,0)\\
8=2^3 &\to (1,0,0,0) & 21=3\cdot7 &\to (0,1,0,1)\\
10=2\cdot5 &\to (1,0,1,0) & 28=2^2\cdot7 &\to (0,0,0,1)\\
12=2^2\cdot3 &\to (0,1,0,0) & 45=3^2\cdot5 &\to (0,0,1,0)\\
15=3\cdot5 &\to (0,1,1,0) & 50=2\cdot5^2 &\to (1,0,0,0)\\
18=2\cdot3^2 &\to (1,0,0,0) & 98=2\cdot7^2 &\to (1,0,0,0)
\end{array}
$$

A subset $T$ has a perfect-square product exactly when the sum (in $\mathbb{F}_2^4$) of the vectors of its elements is $0$.

**Counting the zero-sum subsets.** Let $v_1,\dots,v_{12}$ be these twelve vectors and consider the linear map
$$\Phi:\mathbb{F}_2^{12}\to\mathbb{F}_2^4,\qquad \Phi(x_1,\dots,x_{12})=\sum_i x_i v_i,$$
where $x_i\in\{0,1\}$ indicates membership of the $i$-th element. Square subsets correspond precisely to $\ker\Phi$. Its size is $2^{12-r}$, where $r=\dim\big(\text{span}(v_1,\dots,v_{12})\big)$.

The images include
$$8\to(1,0,0,0),\quad 12\to(0,1,0,0),\quad 20\to(0,0,1,0),\quad 28\to(0,0,0,1),$$
which are the four standard basis vectors, so the span is all of $\mathbb{F}_2^4$ and $r=4$. Therefore the number of square subsets (including the empty set) is
$$2^{12-4}=2^{8}=256.$$

Excluding the empty subset gives
$$256-1=\boxed{255}.$$

**Verification (independent count).** The image of $\Phi$ has dimension $4$, and the fiber over any achievable target has size $|\ker\Phi|=2^{8}=256$; the fiber over $0$ (the square subsets) is the kernel itself, size $256$. Equivalently, choosing which of $8$ "free" coordinates to include and then adjusting the four pivot elements $\{8,12,20,28\}$ to cancel the parities determines each square subset uniquely, giving $2^{8}=256$ subsets, i.e. $255$ nonempty ones. Both routes agree.
</details>

---

## 11. [Combinatorics]  answer = 522   (PE 3.7 / SE 4.2, difficulty 4.5)

For a nonempty set $S$ of positive integers, define its **spread** by
$$\operatorname{sp}(S)=\max(S)-\min(S),$$
so that $\operatorname{sp}(S)=0$ whenever $S$ is a singleton.

Compute
$$\sum_{S}\operatorname{sp}(S),$$
where the sum ranges over **all** nonempty subsets $S$ of $\{1,2,3,4,5,6,7\}$.

*Crux:* Write $\max-\min$ as the number of integers $k$ with $\min\le k<\max$; equivalently split the sum into $\sum\max-\sum\min$ and count how many subsets have a given element as their maximum ($2^{m-1}$) or minimum ($2^{7-m}$).

<details><summary>solution</summary>

Let $n=7$ and write each contribution using linearity:
$$\sum_S \operatorname{sp}(S)=\sum_S\bigl(\max(S)-\min(S)\bigr)=\sum_S \max(S)-\sum_S \min(S).$$

**Counting by the maximum.** An element $m$ is the maximum of a subset $S$ exactly when every other element of $S$ lies in $\{1,\dots,m-1\}$. There are $2^{m-1}$ such subsets. Hence
$$\sum_S \max(S)=\sum_{m=1}^{7} m\,2^{m-1}.$$
Using $\sum_{m=1}^{n} m\,2^{m-1}=(n-1)2^{n}+1$, for $n=7$ this equals $6\cdot 128+1=769$.

**Counting by the minimum.** An element $m$ is the minimum of a subset $S$ exactly when every other element lies in $\{m+1,\dots,7\}$. There are $2^{7-m}$ such subsets. Hence
$$\sum_S \min(S)=\sum_{m=1}^{7} m\,2^{7-m}=64+64+48+32+20+12+7=247.$$

Therefore
$$\sum_S \operatorname{sp}(S)=769-247=\boxed{522}.$$

**Independent check (straddle counting).** Since $\max(S)-\min(S)=\#\{k:\min(S)\le k<\max(S)\}$, we have
$$\sum_S \operatorname{sp}(S)=\sum_{k=1}^{6}\#\{S:\ S\text{ has an element}\le k\text{ and an element}\ge k+1\}.$$
A subset with an element in $\{1,\dots,k\}$ and one in $\{k+1,\dots,7\}$ is chosen by picking a nonempty lower part and a nonempty upper part, giving $(2^{k}-1)(2^{7-k}-1)$ subsets. Thus
$$\sum_{k=1}^{6}(2^{k}-1)(2^{7-k}-1)=\sum_{k=1}^{6}\bigl(2^{7}-2^{k}-2^{7-k}+1\bigr)=6\cdot128-(2^7-2)-(2^7-2)+6=768-126-126+6=522,$$
confirming the answer $522$.
</details>

---

## 12. [Geometry]  answer = 768   (PE 4.3 / SE 4.6, difficulty 5.5)

Let $P$ be a point in the interior of equilateral triangle $ABC$ with
$$PA = 3, \qquad PB = 5, \qquad PC = 7.$$
Find the square of the area of triangle $ABC$.

*Crux:* Rotating $P$ by $60^\circ$ about $A$ (so $B\mapsto C$) collapses the three vertex-distances into a single triangle with sides $3,5,7$; that triangle's $120^\circ$ angle forces three points to be collinear, giving the side directly.

<details><summary>solution</summary>

Rotate the plane by $60^\circ$ about $A$ in the direction that carries $B$ to $C$ (possible since $ABC$ is equilateral). Let $P \mapsto Q$.

**Consequences of the rotation.**
- The rotation preserves distances from $A$, so $AQ = AP = 3$, and since $\angle PAQ = 60^\circ$, triangle $APQ$ is equilateral. Hence $PQ = 3$ and $\angle AQP = 60^\circ$.
- The rotation carries the segment $BP$ to the segment $CQ$, so $CQ = BP = 5$.
- The point $C$ is fixed, and $PC = 7$ is unchanged.

**The auxiliary triangle $PQC$.**
This triangle has sides
$$PQ = 3, \qquad QC = 5, \qquad PC = 7.$$
By the Law of Cosines at vertex $Q$:
$$\cos \angle PQC = \frac{PQ^2 + QC^2 - PC^2}{2\cdot PQ\cdot QC} = \frac{9 + 25 - 49}{2\cdot 3\cdot 5} = \frac{-15}{30} = -\tfrac12,$$
so $\angle PQC = 120^\circ.$

**Collinearity.**
Because $P$ is interior, ray $QP$ lies between rays $QA$ and $QC$, hence
$$\angle AQC = \angle AQP + \angle PQC = 60^\circ + 120^\circ = 180^\circ.$$
Thus $A$, $Q$, $C$ are collinear with $Q$ between $A$ and $C$, and therefore
$$AC = AQ + QC = 3 + 5 = 8.$$

(Equivalently, applying the Law of Cosines in triangle $AQC$ with $\angle AQC = 180^\circ$:
$AC^2 = AQ^2 + QC^2 - 2\cdot AQ\cdot QC\cos 180^\circ = 9 + 25 + 30 = 64$.)

So the side length is $s = AC = 8$. Since $P$ is interior, its distance to each vertex is less than the side length, and indeed $7 < 8$ is consistent; the algebraic alternative $s^2 = 19$ ($s\approx 4.36 < 7$) is impossible for an interior point, confirming uniqueness.

**Area.**
$$[ABC] = \frac{\sqrt3}{4}\,s^2 = \frac{\sqrt3}{4}\cdot 64 = 16\sqrt3.$$
Therefore
$$[ABC]^2 = (16\sqrt3)^2 = 256\cdot 3 = \boxed{768}.$$

**Independent check via the distance identity.** For an interior point of an equilateral triangle of side $s$,
$$3\big(PA^4+PB^4+PC^4+s^4\big) = \big(PA^2+PB^2+PC^2+s^2\big)^2.$$
With $PA^2,PB^2,PC^2 = 9,25,49$: sum $=83$, sum of fourth powers $=81+625+2401=3107$. Let $x=s^2$:
$$3(3107 + x^2) = (83 + x)^2 \Rightarrow 2x^2 - 166x + 2432 = 0 \Rightarrow x^2 - 83x + 1216 = 0,$$
giving $x = \frac{83 \pm 45}{2} = 64 \text{ or } 19.$ The interior root is $x = s^2 = 64$, so $[ABC]^2 = \frac{3}{16}s^4 = \frac{3}{16}\cdot 4096 = 768.$
</details>

---

## 13. [Geometry]  answer = 109   (PE 4.0 / SE 4.3, difficulty 5.0)

Equilateral triangle $ABC$ is inscribed in a circle. Point $P$ lies on the arc $BC$ that does not contain $A$. Given that $PA = 24$ and $PB = 10$, the area of triangle $ABC$ can be written as $m\sqrt{3}$ for a positive integer $m$. Find $m$.

*Crux:* For a point on the arc of an equilateral triangle's circumcircle, Ptolemy gives $PA=PB+PC$, after which the inscribed angle $\angle BPC=120^\circ$ turns the Law of Cosines in $\triangle BPC$ directly into the side length.

<details><summary>solution</summary>

Because $ABC$ is equilateral and $P$ lies on arc $BC$ not containing $A$, the points occur in the cyclic order $A, B, P, C$, so $ABPC$ is a cyclic quadrilateral.

Apply Ptolemy's Theorem to $ABPC$ (diagonals $PA$ and $BC$):
$$PA\cdot BC = PB\cdot AC + PC\cdot AB.$$
Since $AB = BC = CA = s$, this simplifies to
$$PA = PB + PC.$$
Hence $PC = PA - PB = 24 - 10 = 14$.

Next, the inscribed angle $\angle BAC = 60^\circ$ subtends chord $BC$. Point $P$ lies on the opposite arc, so $\angle BPC = 180^\circ - 60^\circ = 120^\circ$.

Now apply the Law of Cosines in triangle $BPC$:
$$s^2 = BC^2 = PB^2 + PC^2 - 2\cdot PB\cdot PC\cos 120^\circ.$$
With $\cos 120^\circ = -\tfrac12$:
$$s^2 = 10^2 + 14^2 - 2(10)(14)\left(-\tfrac12\right) = 100 + 196 + 140 = 436.$$

Therefore the area of $ABC$ is
$$\frac{\sqrt3}{4}s^2 = \frac{\sqrt3}{4}(436) = 109\sqrt3,$$
so $m = 109$.

Check (independent method): For any point $P$ on the circumcircle of an equilateral triangle, the identity $PA^2 + PB^2 + PC^2 = 2s^2$ holds (it equals $6R^2$ with $s^2 = 3R^2$). Using $PA=24,\,PB=10,\,PC=14$:
$$2s^2 = 576 + 100 + 196 = 872 \implies s^2 = 436,$$
giving area $109\sqrt3$ again. Thus $m = \boxed{109}$.
</details>

---

## 14. [Geometry]  answer = 196   (PE 4.0 / SE 4.3, difficulty 5.5)

Let $ABC$ be an equilateral triangle inscribed in a circle $\omega$, and let $P$ be a point on the arc $BC$ of $\omega$ not containing $A$. Suppose that
$$PA = 16 \qquad\text{and}\qquad [\triangle PBC] = 15\sqrt{3},$$
where $[\cdot]$ denotes area. Find the square of the side length of triangle $ABC$.

*Crux:* Ptolemy on the cyclic quadrilateral $ABPC$ gives $PA=PB+PC$, and the inscribed angle forces $\angle BPC=120^\circ$, so the Law of Cosines in $\triangle PBC$ yields $s^2 = PA^2 - PB\cdot PC$.

<details><summary>solution</summary>

Let $PB = x$ and $PC = y$, and let $s$ be the side length of the equilateral triangle, so $AB = BC = CA = s$.

**Step 1: Ptolemy's theorem.**
Since $A, B, P, C$ lie on $\omega$ with $P$ on arc $BC$ not containing $A$, quadrilateral $ABPC$ is cyclic. Ptolemy's theorem gives
$$PA \cdot BC = PB \cdot AC + PC \cdot AB.$$
Since $AB = BC = CA = s$, this reduces to
$$PA = PB + PC \implies x + y = 16.$$

**Step 2: The angle $\angle BPC$.**
Because $P$ and $A$ lie on opposite arcs determined by chord $BC$, the quadrilateral $ABPC$ is cyclic and $\angle BAC + \angle BPC = 180^\circ$. Since $\angle BAC = 60^\circ$,
$$\angle BPC = 120^\circ.$$

**Step 3: Use the area of $\triangle PBC$.**
$$[\triangle PBC] = \tfrac12 \cdot PB \cdot PC \cdot \sin 120^\circ = \tfrac{\sqrt3}{4}\,xy.$$
Setting this equal to $15\sqrt3$:
$$\tfrac{\sqrt3}{4}\,xy = 15\sqrt3 \implies xy = 60.$$

**Step 4: Law of Cosines in $\triangle PBC$.**
Since $BC = s$ and $\angle BPC = 120^\circ$,
$$s^2 = BC^2 = x^2 + y^2 - 2xy\cos 120^\circ = x^2 + y^2 + xy.$$
Now
$$x^2 + y^2 + xy = (x+y)^2 - xy = 16^2 - 60 = 256 - 60 = 196.$$

**Verification (independent computation).**
From $x+y=16,\ xy=60$ we get $\{x,y\}=\{6,10\}$. Then
$$s^2 = x^2 + xy + y^2 = 36 + 60 + 100 = 196,$$
so $s = 14$. Consistency check: the circumradius is $R = s/\sqrt3 = 14/\sqrt3 \approx 8.08$, so the diameter $\approx 16.17 > 16 = PA$, and all chords are valid; the circumradius of $\triangle PBC$ equals $\frac{BC}{2\sin 120^\circ}=\frac{14}{\sqrt3}=R$, confirming $P\in\omega$.

Therefore the square of the side length is $\boxed{196}$.
</details>

---

## 15. [Number Theory]  answer = 165   (PE 4.3 / SE 4.6, difficulty 5.5)

How many integers $n$ with $1 \le n \le 2047$ have the property that the central binomial coefficient $\dbinom{2n}{n}$ is divisible by $8$ but not by $16$?

*Crux:* The exponent of $2$ in $\binom{2n}{n}$ equals $s_2(n)$, the number of $1$'s in the binary representation of $n$.

<details><summary>solution</summary>

We first determine $v_2\!\left(\binom{2n}{n}\right)$, the exponent of $2$ in the central binomial coefficient.

By Legendre's formula, for any positive integer $m$,
$$v_2(m!) = m - s_2(m),$$
where $s_2(m)$ is the number of $1$'s in the binary expansion of $m$. Hence
$$
v_2\!\left(\binom{2n}{n}\right) = v_2((2n)!) - 2\,v_2(n!)
= \big(2n - s_2(2n)\big) - 2\big(n - s_2(n)\big)
= 2\,s_2(n) - s_2(2n).
$$
Multiplying by $2$ merely shifts the binary digits, so $s_2(2n) = s_2(n)$. Therefore
$$
\boxed{v_2\!\left(\binom{2n}{n}\right) = s_2(n).}
$$

(Check: $n=3=11_2$ gives $\binom{6}{3}=20=2^2\cdot5$, and $s_2(3)=2$; $n=7=111_2$ gives $\binom{14}{7}=3432=2^3\cdot429$, and $s_2(7)=3$. Both agree.)

The condition "$\binom{2n}{n}$ divisible by $8$ but not by $16$" means exactly $v_2\!\left(\binom{2n}{n}\right)=3$, i.e. $s_2(n)=3$: the binary representation of $n$ has exactly three $1$'s.

Now count integers $n$ with $1 \le n \le 2047$ and exactly three $1$-bits. Since $2047 = 2^{11}-1 = \underbrace{11\cdots1}_{11}$ in binary, every such $n$ uses bit positions among $\{0,1,\dots,10\}$ (eleven positions). Choosing which three positions hold the $1$'s gives
$$
\binom{11}{3} = 165
$$
numbers. Each is automatically at most $2047$; indeed the largest is $2^{10}+2^{9}+2^{8}=1792 \le 2047$, and the smallest is $2^2+2^1+2^0 = 7 \ge 1$.

Therefore the number of such $n$ is $\boxed{165}$.
</details>

---

## 16. [Number Theory]  answer = 991   (PE 4.3 / SE 4.5, difficulty 5.5)

For a nonnegative integer $n$, the $n$-th Catalan number is
\[
C_n=\frac{1}{n+1}\binom{2n}{n}=\frac{(2n)!}{n!\,(n+1)!}.
\]
Thus $C_0=1,\ C_1=1,\ C_2=2,\ C_3=5,\ C_4=14,\ C_5=42,\ C_6=132,\ C_7=429,\dots$

Determine how many of the Catalan numbers $C_1, C_2, C_3, \ldots, C_{1000}$ are **even**.

*Crux:* The 2-adic valuation of $C_n$ equals $s_2\!\left(\tfrac{n+1}{2^{v_2(n+1)}}-1\right)$, so $C_n$ is odd exactly when $n+1$ is a power of $2$.

<details><summary>solution</summary>

Let $s_2(m)$ denote the number of $1$'s in the binary expansion of $m$, and $v_2(m)$ the exponent of $2$ in $m$.

**Step 1: The 2-adic valuation of the central binomial coefficient.**
By Legendre's formula, $v_2(k!) = k - s_2(k)$. Hence
\[
v_2\binom{2n}{n} = (2n - s_2(2n)) - 2\bigl(n - s_2(n)\bigr) = 2s_2(n) - s_2(2n).
\]
Since doubling in binary just appends a zero, $s_2(2n)=s_2(n)$, so
\[
v_2\binom{2n}{n} = s_2(n).
\]
(Equivalently, this is Kummer's theorem: the number of carries when adding $n+n$ in base $2$ is exactly the number of $1$'s of $n$.)

**Step 2: The 2-adic valuation of $C_n$.**
From $C_n=\frac{1}{n+1}\binom{2n}{n}$,
\[
v_2(C_n) = v_2\binom{2n}{n} - v_2(n+1) = s_2(n) - v_2(n+1).
\]
Write $n+1 = 2^{a}\,X$ with $X$ odd and $a=v_2(n+1)$. Then
\[
n = 2^{a}X - 1 = (X-1)\,2^{a} + (2^{a}-1).
\]
Because $X$ is odd, $X-1$ is even, so $(X-1)2^a$ has all its set bits in positions $\ge a$, while $2^a-1$ occupies positions $0,\dots,a-1$; these do not overlap. Therefore
\[
s_2(n) = s_2(X-1) + a .
\]
Substituting,
\[
v_2(C_n) = \bigl(s_2(X-1)+a\bigr) - a = s_2(X-1).
\]

**Step 3: Characterizing odd Catalan numbers.**
Now $C_n$ is odd $\iff v_2(C_n)=0 \iff s_2(X-1)=0 \iff X-1=0 \iff X=1$, i.e. $n+1 = 2^{a}$.

Thus **$C_n$ is odd exactly when $n+1$ is a power of $2$.** 
(Check: $C_1,C_3,C_7$ are $1,5,429$, all odd, with $n+1 = 2,4,8$; all other listed values are even. ✓)

**Step 4: Counting.**
For $1 \le n \le 1000$, the odd Catalan numbers correspond to $n+1$ being a power of $2$ with $2 \le n+1 \le 1001$:
\[
n+1 \in \{2,4,8,16,32,64,128,256,512\},
\]
that is $n \in \{1,3,7,15,31,63,127,255,511\}$ — exactly $9$ values ($1024$ is excluded since $n=1023>1000$).

Hence the number of **even** Catalan numbers among $C_1,\dots,C_{1000}$ is
\[
1000 - 9 = \boxed{991}.
\]

**Double-check (independent recount):** Powers of two in the interval $[2,1001]$ are $2^1,2^2,\dots,2^9$ (since $2^{10}=1024>1001$), giving $9$ odd terms; the remaining $1000-9=991$ are even. This matches.
</details>

---

## 17. [Number Theory]  answer = 500   (PE 4.3 / SE 4.6, difficulty 5.5)

For each integer $k$ from $1$ to $999$, write $k$ as a three-digit block using leading zeros when necessary (so $1$ becomes $001$, $42$ becomes $042$, and $999$ stays $999$). Concatenate these $999$ blocks in increasing order of $k$ to form one large integer
$$N = \underbrace{001}_{k=1}\,\underbrace{002}_{k=2}\,\underbrace{003}_{k=3}\cdots\underbrace{999}_{k=999}.$$
Find the remainder when $N$ is divided by $1001$.

*Crux:* Since $1000 \equiv -1 \pmod{1001}$, each three-digit block contributes with an alternating sign, collapsing $N \bmod 1001$ to the alternating sum $1-2+3-\cdots+999$.

<details><summary>solution</summary>

Since each number $k$ occupies exactly a three-digit block, and the blocks are placed from most significant (for $k=1$) to least significant (for $k=999$), the numeric value of $N$ is
$$N = \sum_{k=1}^{999} k \cdot 10^{3(999-k)}.$$

Work modulo $1001$. Because $10^3 = 1000 \equiv -1 \pmod{1001}$, we have
$$10^{3(999-k)} = \left(10^3\right)^{999-k} \equiv (-1)^{999-k} \pmod{1001}.$$

Since $999$ is odd, $(-1)^{999-k} = (-1)^{999}(-1)^{-k} = -(-1)^{k} = (-1)^{k+1}$. Therefore
$$N \equiv \sum_{k=1}^{999} (-1)^{k+1}\, k = 1 - 2 + 3 - 4 + \cdots + 999 \pmod{1001}.$$

Grouping in pairs:
$$(1-2)+(3-4)+\cdots+(997-998)+999 = \underbrace{(-1)\cdot 499}_{499\text{ pairs}} + 999 = -499 + 999 = 500.$$

Hence $N \equiv 500 \pmod{1001}$.

**Verification (independent check).** Test the identical method on the smaller concatenation of $1,2,3$: $N' = 001002003 = 1002003$. Directly, $1002003 = 1001\cdot 1001 + 2$, so $N' \equiv 2 \pmod{1001}$. The formula gives $\sum_{k=1}^{3}k\cdot 10^{3(3-k)} \equiv 1\cdot 10^6 + 2\cdot 10^3 + 3 \equiv 1 - 2 + 3 = 2 \pmod{1001}$ (using $10^3\equiv-1$, $10^6\equiv 1$), matching. For an odd upper limit $n$ the alternating sum equals $(n+1)/2$; with $n=999$ this is $500$, confirming the result.

The remainder is $\boxed{500}$.
</details>

---

## 18. [Number Theory]  answer = 48   (PE 4.3 / SE 4.5, difficulty 6.5)

For a positive integer $k$, let $R_k$ denote the **repunit** with $k$ ones, i.e.
$$R_k=\underbrace{11\cdots1}_{k\text{ ones}}=\frac{10^{k}-1}{9}.$$
Find the largest integer $m$ such that $3^{m}$ divides the product
$$R_1\,R_2\,R_3\cdots R_{100}.$$

*Crux:* The 3-adic valuation of a repunit satisfies $v_3(R_k)=v_3(k)$ (via Lifting the Exponent), so the product's valuation collapses to $v_3(100!)$ by Legendre's formula.

<details><summary>solution</summary>

**Step 1: The key valuation identity $v_3(R_k)=v_3(k)$.**

Write $R_k=\dfrac{10^{k}-1}{9}$, so
$$v_3(R_k)=v_3(10^{k}-1)-v_3(9)=v_3(10^{k}-1)-2.$$

Apply the Lifting the Exponent Lemma to $10^{k}-1^{k}$ with prime $p=3$. The hypotheses hold since $3\mid 10-1$ and $3\nmid 10$, $3\nmid 1$. Therefore
$$v_3(10^{k}-1)=v_3(10-1)+v_3(k)=2+v_3(k).$$

Hence
$$v_3(R_k)=\bigl(2+v_3(k)\bigr)-2=v_3(k).$$

(Checks: $R_3=111=3\cdot37$ gives $v_3=1=v_3(3)$; $R_9=111111111=9\cdot12345679$ with $12345679$ not divisible by $3$, so $v_3(R_9)=2=v_3(9)$; $R_1=1,R_2=11$ give $v_3=0$. ✓)

**Step 2: Sum over the product.**

Since $v_3$ is additive over products,
$$m=v_3\!\left(\prod_{k=1}^{100}R_k\right)=\sum_{k=1}^{100}v_3(R_k)=\sum_{k=1}^{100}v_3(k).$$

But $\displaystyle\sum_{k=1}^{100}v_3(k)=v_3(100!)$, the exponent of $3$ in $100!$.

**Step 3: Legendre's formula.**
$$v_3(100!)=\left\lfloor\frac{100}{3}\right\rfloor+\left\lfloor\frac{100}{9}\right\rfloor+\left\lfloor\frac{100}{27}\right\rfloor+\left\lfloor\frac{100}{81}\right\rfloor=33+11+3+1=48.$$

**Verification (alternate route).** By the digit-sum form, $v_3(100!)=\dfrac{100-s_3(100)}{2}$, where $s_3(100)$ is the base-$3$ digit sum. In base $3$, $100=(10201)_3$ since $81+2\cdot9+1=100$, so $s_3(100)=1+0+2+0+1=4$, giving $\dfrac{100-4}{2}=48$. This matches.

Therefore $m=\boxed{48}$.
</details>

---

## 19. [Number Theory]  answer = 319   (PE 4.2 / SE 4.3, difficulty 5.5)

For a positive integer $n$, let $e(n)$ denote the exponent of the highest power of $2$ dividing the central binomial coefficient $\dbinom{2n}{n}$ — that is, the largest integer $k$ such that $2^{k}\mid \dbinom{2n}{n}$.

Compute
\[
\sum_{n=1}^{100} e(n).
\]

*Crux:* By Legendre's digit-sum formula, $v_2\!\binom{2n}{n}=s_2(n)$, the number of $1$'s in the binary representation of $n$, so the sum is just the total number of binary $1$-bits among $1,\dots,100$.

<details><summary>solution</summary>

**Step 1: Reduce $e(n)$ to a digit count.**

Legendre's formula gives, for a prime $p$ and the base-$p$ digit sum $s_p$,
\[
v_p(m!) = \frac{m - s_p(m)}{p-1}.
\]
For $p=2$ this reads $v_2(m!) = m - s_2(m)$. Hence
\[
e(n) = v_2\!\binom{2n}{n} = v_2((2n)!) - 2\,v_2(n!)
= \bigl(2n - s_2(2n)\bigr) - 2\bigl(n - s_2(n)\bigr).
\]
Since doubling a number in binary merely appends a $0$, we have $s_2(2n) = s_2(n)$. Therefore
\[
e(n) = 2n - s_2(n) - 2n + 2 s_2(n) = s_2(n),
\]
the number of $1$'s in the binary expansion of $n$.

(Equivalently, by Kummer's theorem $e(n)$ equals the number of carries when adding $n+n$ in base $2$, which is exactly the number of $1$-bits of $n$.)

**Step 2: Sum the binary digit counts from $1$ to $100$.**

We must compute $\sum_{n=1}^{100} s_2(n)$ (the $n=0$ term is $0$, so summing from $0$ is the same).

*Block $0$–$63$:* Among the $64$ numbers $0,\dots,63$, each of the six bit positions $2^0,\dots,2^5$ is set in exactly $32$ of them. Total $1$-bits:
\[
6 \times 32 = 192.
\]

*Block $64$–$100$:* Write $n = 64 + m$ with $m = 0,1,\dots,36$. Since $m < 64$, the bit $2^6$ contributes once each, and the lower bits contribute $s_2(m)$:
\[
\sum_{m=0}^{36}\bigl(1 + s_2(m)\bigr) = 37 + \sum_{m=0}^{36} s_2(m).
\]
Now $\sum_{m=0}^{31} s_2(m) = 5 \times 16 = 80$ (each of five bits set in $16$ of the $32$ numbers), and for $m=32,\dots,36$:
\[
s_2(32)=1,\ s_2(33)=2,\ s_2(34)=2,\ s_2(35)=3,\ s_2(36)=2,\quad\text{sum}=10.
\]
So $\sum_{m=0}^{36} s_2(m) = 80 + 10 = 90$, giving block total $37 + 90 = 127$.

**Step 3: Combine.**
\[
\sum_{n=1}^{100} e(n) = 192 + 127 = \boxed{319}.
\]

**Independent check (bit-by-bit count over $0$–$100$).** Counting how many of $0,\dots,100$ have each bit set:
bit $0$: $50$; bit $1$: $50$; bit $2$: $49$; bit $3$: $48$; bit $4$: $48$; bit $5$: $37$; bit $6$: $37$; higher: $0$.
Sum $= 50+50+49+48+48+37+37 = 319$, confirming the answer.
</details>

---

## 20. [Number Theory]  answer = 49   (PE 4.2 / SE 4.3, difficulty 5.5)

Call a positive integer $n$ **special** if it has exactly ten digits (its leftmost digit is nonzero, i.e. $10^{9}\le n<10^{10}$) and the last ten digits of $n^{2}$ are exactly the ten digits of $n$; equivalently, $n^{2}$ and $n$ end in the same ten digits.

There are exactly two special numbers, and exactly one of them is even. Find the sum of the decimal digits of the even one.

*Crux:* The condition $n^2\equiv n \pmod{10^{10}}$ means $2^{10}5^{10}\mid n(n-1)$ with $\gcd(n,n-1)=1$, so each prime power lands entirely in $n$ or in $n-1$; the even nontrivial solution is fixed by $2^{10}\mid n,\ 5^{10}\mid n-1$ via CRT.

<details><summary>solution</summary>

A ten‑digit number $n$ has $n$ itself as its last ten digits, so the "special" condition is simply
$$n^{2}\equiv n \pmod{10^{10}}, \qquad 10^{9}\le n<10^{10}.$$

**Reduce to prime powers.** The congruence says $10^{10}\mid n(n-1)$, where $10^{10}=2^{10}\cdot5^{10}$. Since $n$ and $n-1$ are consecutive, $\gcd(n,n-1)=1$; hence each of the coprime prime powers $2^{10}$ and $5^{10}$ must divide $n$ **entirely** or $n-1$ **entirely**. This gives four cases (by the Chinese Remainder Theorem, one solution mod $10^{10}$ each):

1. $2^{10}\mid n,\ 5^{10}\mid n\Rightarrow n\equiv 0$,
2. $2^{10}\mid n-1,\ 5^{10}\mid n-1\Rightarrow n\equiv 1$,
3. $2^{10}\mid n,\ 5^{10}\mid n-1$ (this $n$ is even),
4. $2^{10}\mid n-1,\ 5^{10}\mid n$ (this $n$ is odd, ending in $5$).

Cases 1 and 2 give $n=0,1$, which are not ten‑digit. Cases 3 and 4 give the two special numbers, one even, one odd. We want the **even** one, from Case 3:
$$n\equiv 0 \pmod{2^{10}=1024}, \qquad n\equiv 1 \pmod{5^{10}=9765625}.$$

**Solve by CRT.** Write $n = 1 + 9765625\,t$ and require $1024\mid n$. Now $9765625 = 1024\cdot 9536 + 761$, so $9765625\equiv 761\pmod{1024}$, and we need
$$761\,t \equiv -1 \equiv 1023 \pmod{1024}.$$
The inverse of $761$ mod $1024$ is found by the Euclidean algorithm: $761\cdot 841 = 640001 = 1024\cdot625 + 1$, so $761^{-1}\equiv 841$. Then
$$t \equiv 841\cdot 1023 \equiv 841\cdot(-1) \equiv -841 \equiv 183 \pmod{1024}.$$
Taking $t=183$:
$$n = 1 + 9765625\cdot 183 = 1 + 1787109375 = 1787109376.$$

This lies in $[10^{9},10^{10})$, so it is the desired ten‑digit even special number.

**Verification.** $1787109376 = 1024\cdot 1745224$, so $2^{10}\mid n$ giving $n^2\equiv0\equiv n\pmod{2^{10}}$; and $n-1 = 1787109375 = 9765625\cdot 183$, so $5^{10}\mid n-1$ giving $n\equiv1$, hence $n^2\equiv1\equiv n\pmod{5^{10}}$. Therefore $n^2\equiv n\pmod{10^{10}}$. (Indeed $76,376,9376,\dots,1787109376$ are the classic automorphic numbers.)

**Digit sum.**
$$1+7+8+7+1+0+9+3+7+6 = 49.$$

The answer is $\boxed{49}$.
</details>

---

## 21. [Number Theory]  answer = 256   (PE 4.0 / SE 4.2, difficulty 5.5)

Let $A$ be the positive integer whose decimal representation consists of exactly $36$ consecutive digits equal to $9$ (that is, $A=\underbrace{99\cdots9}_{36}$), and let $B$ be the positive integer whose decimal representation consists of exactly $24$ consecutive nines (that is, $B=\underbrace{99\cdots9}_{24}$).

Find the number of positive integers that divide **both** $A$ and $B$.

*Crux:* The greatest common divisor of two "all-nines" numbers satisfies $\gcd(10^m-1,10^n-1)=10^{\gcd(m,n)}-1$, so the count of common divisors is just the number of divisors of $10^{\gcd(m,n)}-1$.

<details><summary>solution</summary>

Write the two numbers in closed form:
$$A=10^{36}-1,\qquad B=10^{24}-1.$$

**Step 1 — Common divisors correspond to divisors of the gcd.**
For any two positive integers, the set of common divisors of $A$ and $B$ is exactly the set of divisors of $\gcd(A,B)$. Hence the desired count equals $d\big(\gcd(A,B)\big)$, the number of positive divisors of $\gcd(A,B)$.

**Step 2 — Evaluate the gcd using the key identity.**
We use the classical identity
$$\gcd(10^m-1,\,10^n-1)=10^{\gcd(m,n)}-1.$$
*Proof sketch:* Running the Euclidean algorithm on the exponents mirrors the Euclidean algorithm on the numbers, because $10^m-1 = 10^{m-n}(10^n-1) + (10^{m-n}-1)$, so $\gcd(10^m-1,10^n-1)=\gcd(10^n-1,10^{m-n}-1)$; iterating reduces the exponents exactly as $\gcd(m,n)$ is computed.

Since $\gcd(36,24)=12$,
$$\gcd(A,B)=10^{12}-1.$$

**Step 3 — Factor $10^{12}-1$ and count divisors.**
$$10^{12}-1=(10^{6}-1)(10^{6}+1).$$
Now
$$10^{6}-1=999999=999\cdot1001=(3^{3}\cdot 37)(7\cdot 11\cdot 13)=3^{3}\cdot 7\cdot 11\cdot 13\cdot 37,$$
$$10^{6}+1=1000001=101\cdot 9901,$$
where $101$ and $9901$ are prime (checking all primes up to $99$ leaves nonzero remainders for $9901$).

Therefore
$$10^{12}-1=3^{3}\cdot 7\cdot 11\cdot 13\cdot 37\cdot 101\cdot 9901,$$
with prime exponents $(3,1,1,1,1,1,1)$.

The number of positive divisors is
$$d(10^{12}-1)=(3+1)(1+1)^{6}=4\cdot 64=256.$$

**Verification (independent recomputation).**
Split the divisor count multiplicatively across the two factors:
- $999999=3^{3}\cdot7\cdot11\cdot13\cdot37$ has $(3+1)\cdot2^{4}=4\cdot16=64$ divisors,
- $1000001=101\cdot9901$ has $2\cdot2=4$ divisors.

Because $\gcd(999999,1000001)=1$ (they are coprime — one more than the other, and consecutive-type factors share no prime), the divisor counts multiply:
$$64\times 4 = 256.$$

Both methods agree.

**Answer:** $\boxed{256}$.
</details>

---

## 22. [Number Theory]  answer = 105   (PE 4.0 / SE 4.2, difficulty 5.5)

For a positive integer $n$, let $\binom{2n}{n}$ denote the central binomial coefficient. Find the number of integers $n$ with $1 \le n \le 1000$ for which $\binom{2n}{n}$ is **not** divisible by $3$.

*Crux:* By Kummer's theorem, $3 \nmid \binom{2n}{n}$ exactly when adding $n+n$ in base $3$ produces no carries, which happens iff every base-3 digit of $n$ is $0$ or $1$.

<details><summary>solution</summary>

**Reformulating divisibility via Kummer's theorem.**
Kummer's theorem states that the exponent of a prime $p$ in $\binom{m+k}{k}$ equals the number of carries when adding $m$ and $k$ in base $p$. Taking $m=k=n$ and $p=3$, the exponent of $3$ in $\binom{2n}{n}$ equals the number of carries in the base-3 addition $n+n$.

Thus $\binom{2n}{n}$ is **not** divisible by $3$ exactly when this addition has **no** carries.

Write $n=\sum_i d_i 3^i$ with digits $d_i\in\{0,1,2\}$. Adding $n+n$ in base $3$, the value at position $i$ before carrying is $2d_i + c_i$ where $c_i$ is the incoming carry. If all digits satisfy $d_i\le 1$, then $2d_i\le 2<3$ with no incoming carry, so no carry is ever produced. Conversely, if some digit equals $2$, then $2\cdot 2 = 4\ge 3$ forces a carry. Hence:
$$3 \nmid \binom{2n}{n} \iff \text{every base-3 digit of } n \text{ lies in } \{0,1\}.$$

**Counting such $n$ in $[1,1000]$.**
Since $3^6 = 729 \le 1000 < 2187 = 3^7$, the relevant powers are $3^0,\dots,3^6$. Numbers whose base-3 digits are all $0$ or $1$ correspond exactly to sums
$$\sum_{i\in S} 3^i,\qquad S\subseteq\{0,1,2,3,4,5,6\},$$
and each subset gives a distinct value (uniqueness of base-3 representation). We must count nonempty subsets $S$ with $\sum_{i\in S}3^i \le 1000$.

The full set gives $3^0+\cdots+3^6 = \frac{3^7-1}{2} = 1093$. So some subsets exceed $1000$; count those with sum $>1000$.

- To exceed $1000$ we must include $3^6=729$ (without it the maximum is $243+81+27+9+3+1=364$).
- Given $729\in S$, we need the rest to exceed $271$. We must include $243$ (without it the rest max is $121$).
- Given $\{729,243\}\subseteq S$, we need a subset of $\{81,27,9,3,1\}$ with sum $\ge 29$.

Counting subsets of $\{81,27,9,3,1\}$ with sum $\ge 29$:
- Including $81$: all $16$ subsets of the remaining $\{27,9,3,1\}$ work (sum $\ge 81$).
- Excluding $81$: need subset of $\{27,9,3,1\}$ with sum $\ge 29$. Must include $27$; then need $\{9,3,1\}$-subset summing $\ge 2$, i.e. all $8$ except $\{\}$ and $\{1\}$, giving $6$.

Total: $16+6 = 22$ subsets exceed $1000$.

There are $2^7 = 128$ subsets total, so subsets with sum $\le 1000$ number $128 - 22 = 106$, including the empty set (value $0$). Excluding it leaves
$$106 - 1 = 105$$
valid integers $n$ with $1\le n\le 1000$.

**Sanity check (small range).** For $1\le n\le 3$: $n=1=(1)_3$ and $n=3=(10)_3$ have digits $\le 1$, while $n=2=(2)_3$ does not. Indeed $\binom21=2,\ \binom63=20$ are not divisible by $3$, but $\binom42=6$ is — matching exactly $2$ valid values.

**Answer:** $\boxed{105}$.
</details>

---

## 23. [Number Theory]  answer = 207   (PE 4.0 / SE 4.0, difficulty 5.5)

The decimal expansion of $\dfrac{1}{47}$ is purely periodic. Writing one full period as a string of digits (including any leading zeros, so that the string has length equal to the minimal period), find the sum of all the digits in that period.

*Crux:* Midy's theorem: for a prime $p$ whose period length $L$ is even, the two halves of the repeating block are digit-wise $9$-complements, so the digit sum is $9L/2$ — reducing the problem to finding $\operatorname{ord}_{47}(10)$.

<details><summary>solution</summary>

Since $\gcd(47,10)=1$, the expansion of $1/47$ is purely periodic with minimal period length $L=\operatorname{ord}_{47}(10)$.

**Step 1: Find the period length.**
Because $47$ is prime, $\operatorname{ord}_{47}(10)\mid 46=2\cdot 23$, so $L\in\{1,2,23,46\}$. Compute powers of $10$ modulo $47$:
$$10^1\equiv 10,\quad 10^2\equiv 100\equiv 6,\quad 10^4\equiv 6^2=36,$$
$$10^8\equiv 36^2=1296\equiv 27,\quad 10^{16}\equiv 27^2=729\equiv 24.$$
Then
$$10^{23}=10^{16}\cdot10^{4}\cdot10^{2}\cdot10^{1}\equiv 24\cdot36\cdot6\cdot10.$$
Now $24\cdot36=864\equiv 18$, $18\cdot6=108\equiv 14$, $14\cdot10=140\equiv 46\equiv -1\pmod{47}.$
Thus $10^{23}\equiv -1\not\equiv 1$, so the order does not divide $23$; hence $L=46$.

**Step 2: Split the period into halves.**
Let $N$ be the $46$-digit integer formed by one period (with leading zeros). Since a purely periodic block satisfies
$$\frac{1}{47}=\frac{N}{10^{46}-1},\qquad N=\frac{10^{46}-1}{47}.$$
Write $N=A\cdot 10^{23}+B$ with $0\le B<10^{23}$, so $A$ is the first-half integer and $B$ the second half.

From $10^{23}\equiv -1\pmod{47}$ we have $10^{23}=47A+46$ where $A=\lfloor 10^{23}/47\rfloor$, i.e. $A=\dfrac{10^{23}-46}{47}$. Then
$$47B=47N-47A\cdot10^{23}=(10^{46}-1)-(10^{23}-46)10^{23}=46\cdot10^{23}-1,$$
so $B=\dfrac{46\cdot10^{23}-1}{47}$. Adding,
$$A+B=\frac{(10^{23}-46)+(46\cdot10^{23}-1)}{47}=\frac{47\cdot10^{23}-47}{47}=10^{23}-1=\underbrace{9\cdots9}_{23}.$$

**Step 3: No carries, so digits are complementary.**
Both $A,B<10^{23}$ and $A+B=10^{23}-1$. In the lowest column $a_0+b_0=9+10c_1$; since $a_0+b_0\le 18$ we must have $c_1=0$ and $a_0+b_0=9$. Inductively, with incoming carry $0$ each column gives $a_i+b_i=9$ and carry-out $0$ (a carry-out would require $a_i+b_i+c_i=19$, i.e. $a_i=b_i=9,c_i=1$, contradicting $c_i=0$). Hence every corresponding pair of digits sums to $9$.

**Step 4: Digit sum.**
Therefore the total digit sum of the period is
$$\text{(digit sum of }A)+\text{(digit sum of }B)=23\cdot 9=207.$$

(As a check, $L/2\cdot 9=23\cdot9=207$, matching Midy's theorem directly.)

The sum of the digits in one full period of $1/47$ is $\boxed{207}$.
</details>

---

## 24. [Number Theory]  answer = 250   (PE 4.0 / SE 4.3, difficulty 5.5)

For a positive integer $n$, write $n$ in base $7$ as
$$n = d_k\,7^k + d_{k-1}\,7^{k-1} + \cdots + d_1\,7 + d_0,\qquad 0\le d_i\le 6.$$
Define
$$S(n) = d_0 + d_1 + \cdots + d_k \qquad\text{(the digit sum)},$$
$$A(n) = d_0 - d_1 + d_2 - \cdots + (-1)^k d_k \qquad\text{(the alternating digit sum)}.$$
Find the number of integers $n$ with $1 \le n \le 6000$ such that $S(n)$ is divisible by $6$ **and** $A(n)$ is divisible by $8$.

*Crux:* Since $7\equiv 1\pmod 6$ and $7\equiv -1\pmod 8$, the base-7 digit sum and alternating digit sum satisfy $S(n)\equiv n\pmod 6$ and $A(n)\equiv n\pmod 8$, so the two conditions are just $6\mid n$ and $8\mid n$.

<details><summary>solution</summary>

Write $n=\sum_{i=0}^k d_i 7^i$ in base $7$.

**Reducing the first condition.** Because $7\equiv 1\pmod 6$, every power $7^i\equiv 1\pmod 6$. Hence
$$n=\sum_{i} d_i 7^i \equiv \sum_i d_i = S(n)\pmod 6.$$
Therefore $6\mid S(n)$ if and only if $6\mid n$.

**Reducing the second condition.** Because $7\equiv -1\pmod 8$, we have $7^i\equiv(-1)^i\pmod 8$. Hence
$$n=\sum_i d_i 7^i \equiv \sum_i (-1)^i d_i = A(n)\pmod 8.$$
Therefore $8\mid A(n)$ if and only if $8\mid n$. (This holds regardless of the sign convention chosen for $A$, since negating a number does not affect divisibility by $8$.)

**Combining.** The two conditions are equivalent to $6\mid n$ and $8\mid n$, i.e. to
$$\operatorname{lcm}(6,8)=24 \mid n.$$

**Counting.** The multiples of $24$ in $[1,6000]$ are $24,48,\dots,6000$, and since $6000=24\cdot 250$, there are exactly
$$\left\lfloor \frac{6000}{24}\right\rfloor = 250$$
of them.

**Verification (independent recount).** A number in $[1,6000]$ satisfies both $2^3\mid n$ and $3\mid n$ (from $8\mid n$ and $6\mid n$, whose combined content is $24\mid n$). Counting directly: multiples of $8$ up to $6000$ number $750$; among these, those also divisible by $3$ occur every third one, giving $750/3=250$. This matches.

The answer is $\boxed{250}$.
</details>

---

## 25. [Number Theory]  answer = 448   (PE 4.0 / SE 4.5, difficulty 5.5)

Let 
$$N=\prod_{n=1}^{127}\binom{2n}{n}=\binom{2}{1}\binom{4}{2}\binom{6}{3}\cdots\binom{254}{127}.$$
Find the largest integer $k$ such that $2^{k}\mid N$.

*Crux:* By Legendre's formula the 2-adic valuation of a central binomial coefficient collapses to a binary digit sum: $v_2\binom{2n}{n}=s_2(n)$, so the whole product's valuation is $\sum_{n=1}^{127}s_2(n)$.

<details><summary>solution</summary>

Write $s_2(m)$ for the number of $1$'s in the binary expansion of $m$. Legendre's formula gives, for any prime $p$,
$$v_p(m!)=\frac{m-s_p(m)}{p-1},\qquad\text{so } v_2(m!)=m-s_2(m).$$

For each $n$,
$$
v_2\binom{2n}{n}=v_2\big((2n)!\big)-2\,v_2(n!)
=\big(2n-s_2(2n)\big)-2\big(n-s_2(n)\big)
=2s_2(n)-s_2(2n).
$$
Since multiplying by $2$ merely appends a zero bit, $s_2(2n)=s_2(n)$. Hence
$$
v_2\binom{2n}{n}=s_2(n).
$$

Therefore
$$
k=v_2(N)=\sum_{n=1}^{127}v_2\binom{2n}{n}=\sum_{n=1}^{127}s_2(n).
$$

Now $127=2^{7}-1$, so the integers $0,1,\dots,127$ range over all $7$-bit binary strings. In each of the $7$ bit positions, a $1$ occurs in exactly half of the $128$ numbers, i.e. in $64$ of them. Thus
$$
\sum_{n=0}^{127}s_2(n)=7\cdot 64=448,
$$
and since $s_2(0)=0$ we also have $\sum_{n=1}^{127}s_2(n)=448$.

**Cross-check (Kummer's theorem).** $v_2\binom{2n}{n}$ equals the number of carries when adding $n+n$ in base $2$. Small cases: $n=1$ gives $1$ carry ($=s_2(1)$); $n=3=(11)_2$ gives $2$ carries ($=s_2(3)$); $n=7=(111)_2$ gives $3$ carries ($=s_2(7)$). This confirms $v_2\binom{2n}{n}=s_2(n)$ independently, and the digit-count sum again yields $448$.

Hence $k=\boxed{448}$.
</details>

---

## 26. [Number Theory]  answer = 55   (PE 4.0 / SE 4.3, difficulty 5.5)

Find the number of ordered pairs $(a,b)$ of positive integers such that
$$\gcd(a,b) + \operatorname{lcm}(a,b) = 2024.$$

*Crux:* Writing $a=gx,\,b=gy$ with $\gcd(x,y)=1$ turns the condition into $g(1+xy)=2024$, so for each divisor $g$ the number of valid coprime factorizations $xy=2024/g-1$ is $2^{\omega(\cdot)}$.

<details><summary>solution</summary>

Let $g=\gcd(a,b)$ and write $a=gx,\ b=gy$ with $\gcd(x,y)=1$. Then $\operatorname{lcm}(a,b)=gxy$, so the equation becomes
$$g + gxy = g(1+xy) = 2024.$$

Hence $g\mid 2024$, and setting $d=\tfrac{2024}{g}$ (which is also a divisor of $2024$) we need
$$xy = d-1,\qquad \gcd(x,y)=1,\qquad x,y\ge 1.$$
This requires $d\ge 2$.

**Counting coprime factorizations.** For a positive integer $m$, the number of *ordered* pairs $(x,y)$ with $xy=m$ and $\gcd(x,y)=1$ is $2^{\omega(m)}$, where $\omega(m)$ is the number of distinct prime factors of $m$ (each prime-power block of $m$ goes entirely to $x$ or entirely to $y$). For $m=1$ this gives $2^0=1$, namely $(1,1)$.

Since distinct values of $g$ give distinct $\gcd$'s, the pairs produced are all distinct. Therefore
$$\#\{(a,b)\} \;=\; \sum_{\substack{d\mid 2024\\ d\ge 2}} 2^{\omega(d-1)}.$$

**Computation.** Factor $2024=2^3\cdot 11\cdot 23$. Its divisors $d\ge 2$ and the values $2^{\omega(d-1)}$:

| $d$ | $d-1$ | factorization | $2^{\omega(d-1)}$ |
|---|---|---|---|
|2|1|$1$|1|
|4|3|$3$|2|
|8|7|$7$|2|
|11|10|$2\cdot5$|4|
|22|21|$3\cdot7$|4|
|23|22|$2\cdot11$|4|
|44|43|$43$|2|
|46|45|$3^2\cdot5$|4|
|88|87|$3\cdot29$|4|
|92|91|$7\cdot13$|4|
|184|183|$3\cdot61$|4|
|253|252|$2^2\cdot3^2\cdot7$|8|
|506|505|$5\cdot101$|4|
|1012|1011|$3\cdot337$|4|
|2024|2023|$7\cdot17^2$|4|

Summing the last column:
$$1+2+2+4+4+4+2+4+4+4+4+8+4+4+4 = 55.$$

**Cross-check.** Grouping by $g$ instead of $d$ gives the identical multiset of terms (e.g. $g=8\Rightarrow d=253\Rightarrow 2^{\omega(252)}=8$), and the running total $1,3,5,9,13,17,19,23,27,31,35,43,47,51,55$ again yields $55$.

Thus the number of ordered pairs is $\boxed{55}$.
</details>

---

## 27. [Number Theory]  answer = 30   (PE 3.8 / SE 4.0, difficulty 5.5)

Find the sum of the digits of the six-digit string formed by the last six digits of 
$$5^{\,2^{100}}.$$
(Here the "last six digits" are the residue of $5^{2^{100}}$ modulo $10^6$, written as a six-digit number.)

*Crux:* The powers $5^{2^k}$ stabilize $10$-adically to the automorphic idempotent $\equiv 0 \pmod{5^n}$, $\equiv 1 \pmod{2^n}$, because the order of $5$ modulo a power of $2$ is itself a power of $2$; via CRT this pins the last six digits to $890625$.

<details><summary>solution</summary>

We must compute $5^{2^{100}} \pmod{10^6}$, using $10^6 = 2^6\cdot 5^6 = 64\cdot 15625$ and the Chinese Remainder Theorem.

**Modulo $5^6$.** Since the exponent $2^{100}\ge 6$, the number $5^{2^{100}}$ is divisible by $5^{6}$. Hence
$$5^{2^{100}} \equiv 0 \pmod{5^6}.$$

**Modulo $2^6 = 64$.** Here $5$ is a unit. The multiplicative order of $5$ modulo $2^6$ is a power of two: indeed $5^{2}=25,\ 5^{4}\equiv 49,\ 5^{8}\equiv 49^2=2401\equiv 33,\ 5^{16}\equiv 33^2=1089\equiv 1 \pmod{64}$, so the order is $16$. Because $2^{100}$ is a multiple of $16$,
$$5^{2^{100}} \equiv 5^{0} \equiv 1 \pmod{64}.$$

**Combine with CRT.** We need the unique $N \pmod{10^6}$ with
$$N \equiv 0 \pmod{15625}, \qquad N \equiv 1 \pmod{64}.$$
Write $N = 15625\,t$. Since $15625 = 244\cdot 64 + 9$, we have $15625\equiv 9 \pmod{64}$, so we need $9t \equiv 1 \pmod{64}$. As $9\cdot 57 = 513 = 8\cdot 64 + 1$, the inverse of $9$ is $57$, giving $t \equiv 57 \pmod{64}$. Taking $t = 57$:
$$N = 15625\cdot 57 = 890625.$$
Thus the last six digits of $5^{2^{100}}$ are $890625$.

**Independent check.** Compute $5^{16} = 152587890625$, whose last six digits are $890625$. Since both $16$ and $2^{100}$ are multiples of the order $16$ (giving residue $1 \pmod{64}$) and both exponents are $\ge 6$ (giving residue $0 \pmod{5^6}$), we have $5^{2^{100}} \equiv 5^{16} \pmod{10^6}$, confirming $890625$. (Indeed $890625$ is automorphic: $890625^2$ ends in $890625$.)

**Answer.** The digit sum is
$$8+9+0+6+2+5 = 30.$$
</details>

---

## 28. [Number Theory]  answer = 140   (PE 3.7 / SE 4.2, difficulty 6.0)

For each integer $k$ with $1 \le k \le 2520$, let
$$g_k = \gcd(k,\,2520).$$
Find the remainder when $\displaystyle\sum_{k=1}^{2520} g_k$ is divided by $1000$.

*Crux:* Grouping the terms by the value of $\gcd(k,n)$ turns $\sum_{k=1}^n\gcd(k,n)$ into the multiplicative function $\sum_{d\mid n} d\,\varphi(n/d)$, computable prime-power by prime-power.

<details><summary>solution</summary>

Let $n = 2520$ and define $S(n)=\sum_{k=1}^{n}\gcd(k,n)$.

**Reformulation (the key step).** Sort the terms according to the actual value of the gcd. Every value $d=\gcd(k,n)$ is a divisor of $n$. For a fixed divisor $d\mid n$, the number of integers $k\in\{1,\dots,n\}$ with $\gcd(k,n)=d$ equals the number of $j\in\{1,\dots,n/d\}$ with $\gcd(j,\,n/d)=1$ (write $k=dj$), which is exactly $\varphi(n/d)$. Hence
$$
S(n)=\sum_{k=1}^{n}\gcd(k,n)=\sum_{d\mid n} d\,\varphi\!\left(\tfrac{n}{d}\right).
$$
This is the Dirichlet convolution $S = \mathrm{Id}*\varphi$ of two multiplicative functions, so $S$ is **multiplicative**.

**Value at a prime power.** For a prime power $p^e$,
$$
S(p^e)=\sum_{j=0}^{e} p^{\,j}\,\varphi(p^{\,e-j})
= p^e + \sum_{j=0}^{e-1} p^{\,j}\bigl(p^{\,e-j}-p^{\,e-j-1}\bigr)
= p^e + e\,(p^e-p^{e-1}),
$$
i.e. $S(p^e) = (e+1)p^e - e\,p^{e-1}$.

**Computation.** Since $2520 = 2^3\cdot 3^2\cdot 5\cdot 7$,
$$
S(8)=(4)8-(3)4=32-12=20,\qquad
S(9)=(3)9-(2)3=27-6=21,
$$
$$
S(5)=2\cdot5-1=9,\qquad
S(7)=2\cdot7-1=13.
$$
(Check directly, e.g. $\sum_{k=1}^{8}\gcd(k,8)=1+2+1+4+1+2+1+8=20$, and $\sum_{k=1}^{7}\gcd(k,7)=6\cdot1+7=13$.)

By multiplicativity,
$$
S(2520)=20\cdot 21\cdot 9\cdot 13.
$$
Compute: $20\cdot21=420$, $420\cdot9=3780$, $3780\cdot13=49140$.

**Verification.** Recomputing the product in a different order: $9\cdot13=117$, $20\cdot117=2340$, $2340\cdot21 = 49140$ — same value. Thus $S(2520)=49140$.

Finally,
$$
49140 \equiv \boxed{140} \pmod{1000}.
$$
</details>

---

## 29. [Precalculus]  answer = 200   (PE 4.3 / SE 4.0, difficulty 5.5)

A regular $49$-gon $P_1P_2P_3\cdots P_{49}$ is inscribed in a circle of radius $1$. Compute
$$\sum_{k=2}^{49}\frac{1}{\left(P_1P_k\right)^2}.$$

*Crux:* The reciprocal squared chord-lengths from one vertex reduce to $\tfrac14\sum_{j=1}^{n-1}\csc^2\frac{j\pi}{n}=\tfrac{n^2-1}{12}$, where the cosecant-square sum is evaluated by Vieta's formulas on the polynomial whose roots are $\cot^2\frac{j\pi}{n}$.

<details><summary>solution</summary>

**Step 1: Express the chords.**
Place the polygon on a circle of radius $1$. The central angle subtended by $P_1$ and $P_k$ is $\frac{2\pi(k-1)}{49}$, so the chord length is
$$P_1P_k = 2\sin\!\frac{(k-1)\pi}{49}.$$
Hence
$$\sum_{k=2}^{49}\frac{1}{(P_1P_k)^2}=\sum_{k=2}^{49}\frac{1}{4\sin^2\frac{(k-1)\pi}{49}}=\frac14\sum_{j=1}^{48}\csc^2\frac{j\pi}{49}.$$

So everything reduces to evaluating $\displaystyle S=\sum_{j=1}^{48}\csc^2\frac{j\pi}{49}$.

**Step 2: Evaluate $\sum \cot^2$ by Vieta.**
Write $n=49=2m+1$ with $m=24$. By De Moivre,
$$\sin(n\theta)=\operatorname{Im}\big((\cos\theta+i\sin\theta)^n\big)=\sum_{k=0}^{m}\binom{n}{2k+1}(-1)^k\cos^{\,n-2k-1}\theta\,\sin^{2k+1}\theta.$$
Dividing by $\sin^{n}\theta$ (and using that $n-2k-1$ is even since $n$ is odd, so $\cot^{\,n-2k-1}\theta=(\cot^2\theta)^{m-k}$):
$$\frac{\sin n\theta}{\sin^{n}\theta}=\sum_{k=0}^{m}\binom{n}{2k+1}(-1)^k\,t^{\,m-k}=:P(t),\qquad t=\cot^2\theta,$$
a polynomial of degree $m$ with leading coefficient $\binom{n}{1}=n$ and next coefficient $-\binom{n}{3}$.

For $\theta_j=\frac{j\pi}{n}$ with $j=1,\dots,m$, we have $\sin(n\theta_j)=\sin(j\pi)=0$ but $\sin\theta_j\neq0$, so $P(\cot^2\theta_j)=0$. These give $m$ distinct roots $t_j=\cot^2\frac{j\pi}{n}$, exactly filling $P$. By Vieta,
$$\sum_{j=1}^{m}\cot^2\frac{j\pi}{n}=\frac{\binom{n}{3}}{\binom{n}{1}}=\frac{(n-1)(n-2)}{6}.$$
For $n=49$: $\displaystyle\sum_{j=1}^{24}\cot^2\frac{j\pi}{49}=\frac{48\cdot47}{6}=376.$

Since $\cot^2\frac{(n-j)\pi}{n}=\cot^2\frac{j\pi}{n}$, the full sum over $j=1,\dots,48$ is double:
$$\sum_{j=1}^{48}\cot^2\frac{j\pi}{49}=2\cdot376=752.$$

**Step 3: Convert to $\csc^2$.**
Using $\csc^2=1+\cot^2$,
$$S=\sum_{j=1}^{48}\csc^2\frac{j\pi}{49}=752+48=800,$$
consistent with the general identity $\sum_{j=1}^{n-1}\csc^2\frac{j\pi}{n}=\frac{n^2-1}{3}=\frac{49^2-1}{3}=\frac{2400}{3}=800.$

**Step 4: Finish.**
$$\sum_{k=2}^{49}\frac{1}{(P_1P_k)^2}=\frac14\,S=\frac{800}{4}=200.$$

**Cross-check (small cases of the identity used).**
For a square ($n=4$, radius $1$): distances from one vertex are $\sqrt2,\,2,\,\sqrt2$, giving $\tfrac12+\tfrac14+\tfrac12=\tfrac54=\frac{4^2-1}{12}$. For an equilateral triangle ($n=3$): $\tfrac13+\tfrac13=\tfrac23=\frac{3^2-1}{12}$. Both match $\frac{n^2-1}{12}$, and for $n=49$ this gives $\frac{2400}{12}=200$.

The answer is $\boxed{200}$.
</details>

---

## 30. [Probability]  answer = 495   (PE 4.2 / SE 4.5, difficulty 5.5)

Forty-five students form a class. A "note-passing scheme" is created by choosing a uniformly random permutation $\sigma$ of the students (all $45!$ permutations equally likely); student $i$ is required to pass any note in hand to student $\sigma(i)$. If a note is started by student $i$, it travels
$$i \to \sigma(i) \to \sigma(\sigma(i)) \to \cdots$$
and eventually returns to $i$.

Call two **distinct** students *linked* if a note started by one of them passes through the other before it first returns to its originator.

Find the expected number of linked (unordered) pairs of students.

*Crux:* In a uniformly random permutation the cycle containing a fixed element has length uniform on $\{1,\dots,n\}$, so any two distinct elements lie in a common cycle with probability exactly $\tfrac12$.

<details><summary>solution</summary>

Following the note from a student $i$ traces out exactly the cycle of $\sigma$ containing $i$. Thus two distinct students $i,j$ are *linked* precisely when $i$ and $j$ lie in the **same cycle** of $\sigma$ (linkage is symmetric: if $j$ is in $i$'s cycle then $i$ is in $j$'s cycle).

For each unordered pair $\{i,j\}$ with $i\ne j$, let $X_{ij}=1$ if they share a cycle, else $0$. By linearity of expectation, the expected number of linked pairs is
$$
\sum_{\{i,j\}} \Pr(i,j \text{ same cycle}) = \binom{45}{2}\,\Pr(i,j \text{ same cycle}),
$$
using that this probability is the same for every pair.

**Key claim:** For a uniformly random permutation of $n$ elements, $\Pr(i,j \text{ same cycle}) = \tfrac12$.

*Step 1 — the cycle length containing $i$ is uniform.* Count permutations in which $i$ lies in a cycle of length $\ell$. Such a cycle is
$$i \to a_1 \to a_2 \to \cdots \to a_{\ell-1} \to i,$$
where $a_1,\dots,a_{\ell-1}$ are distinct elements chosen from the other $n-1$: there are $(n-1)(n-2)\cdots(n-\ell+1) = \tfrac{(n-1)!}{(n-\ell)!}$ ordered choices. The remaining $n-\ell$ elements may be permuted freely in $(n-\ell)!$ ways. Hence the number of such permutations is
$$
\frac{(n-1)!}{(n-\ell)!}\cdot (n-\ell)! = (n-1)!,
$$
**independent of $\ell$.** So each length $\ell\in\{1,\dots,n\}$ occurs with probability $\tfrac{(n-1)!}{n!}=\tfrac1n$; the cycle length $L$ of $i$ is uniform on $\{1,\dots,n\}$.

*Step 2 — conditioning.* Given that $i$'s cycle has length $\ell$, its other $\ell-1$ members form a uniformly random subset of the remaining $n-1$ students, so $\Pr(j \in i\text{'s cycle}\mid L=\ell) = \tfrac{\ell-1}{n-1}$. Therefore
$$
\Pr(i,j \text{ same cycle}) = \sum_{\ell=1}^{n}\frac1n\cdot\frac{\ell-1}{n-1}
= \frac{1}{n(n-1)}\sum_{\ell=1}^{n}(\ell-1)
= \frac{1}{n(n-1)}\cdot\frac{(n-1)n}{2} = \frac12 .
$$

**Finish.** With $n=45$,
$$
\binom{45}{2}\cdot\frac12 = \frac{990}{2} = 495 .
$$

**Independent check.** Let $L_c$ denote cycle lengths. The number of linked pairs equals $\sum_c \binom{L_c}{2} = \tfrac12\big(\sum_c L_c^2 - n\big)$. Now $\sum_c L_c^2$ counts ordered pairs $(a,b)$ in a common cycle (including $a=b$); its expectation is $n + n(n-1)\cdot\tfrac12 = \tfrac{n(n+1)}{2}$. For $n=45$ this is $\tfrac{45\cdot46}{2}=1035$, giving $\tfrac{1035-45}{2}=\tfrac{990}{2}=495$, confirming the answer.

$$\boxed{495}$$
</details>

---
