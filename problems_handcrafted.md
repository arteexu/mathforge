# Hand-crafted problems (opus-hc)

## opus-hc-001 — Combinatorics  (difficulty 5.0, elegance 4)

In how many ways can a $2\times 10$ rectangle be tiled using any combination of $1\times 2$ dominoes (in either orientation) and $2\times 2$ squares?

**Answer:** 683  
**Crux:** Case on the left edge: a vertical domino leaves 2x9; two stacked horizontals or a 2x2 square each leave 2x8, giving a(n)=a(n-1)+2a(n-2).

<details><summary>Solution</summary>

Let $a(n)$ count tilings of a $2\times n$. The first column is a vertical domino ($a(n-1)$), or the first two columns are two horizontal dominoes or a $2\times2$ square ($2a(n-2)$). With $a(0)=a(1)=1$, $a(10)=683$.

</details>


---

## opus-hc-002 — Algebra  (difficulty 4.0, elegance 4)

The product $\displaystyle\prod_{k=2}^{100}\left(1-\frac{1}{k^2}\right)$ equals $\frac{m}{n}$ in lowest terms. Find $m+n$.

**Answer:** 301  
**Crux:** 1-1/k^2 = (k-1)(k+1)/k^2 telescopes as a product.

<details><summary>Solution</summary>

$1-\frac1{k^2}=\frac{(k-1)(k+1)}{k^2}$, so the product telescopes to $\frac12\cdot\frac{101}{100}=\frac{101}{200}$. Thus $m+n=301$.

</details>


---

## opus-hc-003 — Combinatorics  (difficulty 4.5, elegance 4)

How many $5$-digit numbers (no leading zero) have digits that are either strictly increasing or strictly decreasing from left to right?

**Answer:** 378  
**Crux:** A strictly monotone number is determined by its digit set.

<details><summary>Solution</summary>

Increasing: choose $5$ of $\{1,\dots,9\}$ (0 cannot appear): $\binom95=126$. Decreasing: choose $5$ of $\{0,\dots,9\}$, largest leads so it's nonzero: $\binom{10}{5}=252$. No overlap; total $378$.

</details>


---

## opus-hc-004 — Algebra  (difficulty 4.0, elegance 3)

A real number $x$ satisfies $x+\dfrac1x=3$. Find $x^5+\dfrac1{x^5}$.

**Answer:** 123  
**Crux:** s_n = x^n + x^{-n} satisfies s_n = 3 s_{n-1} - s_{n-2}.

<details><summary>Solution</summary>

With $s_1=3$: $s_2=7,\ s_3=18,\ s_4=47,\ s_5=3\cdot47-18=123$.

</details>


---

## opus-hc-005 — Number Theory  (difficulty 4.5, elegance 4)

How many integers from $1$ to $1000$ are divisible by none of $6$, $10$, and $15$?

**Answer:** 734  
**Crux:** All three pairwise LCMs and the triple LCM equal 30, so inclusion-exclusion collapses.

<details><summary>Solution</summary>

$166+100+66-33-33-33+33=266$ are divisible by at least one; $1000-266=734$.

</details>


---

## opus-hc-006 — Combinatorics  (difficulty 5.5, elegance 4)

How many lattice paths from $(0,0)$ to $(6,6)$ using unit right/up steps never rise above the line $y=x$?

**Answer:** 132  
**Crux:** These are counted by the Catalan number C_6.

<details><summary>Solution</summary>

Such paths number $C_6=\frac{1}{7}\binom{12}{6}=132$.

</details>


---

## opus-hc-007 — Number Theory  (difficulty 5.0, elegance 4)

How many trailing zeros does $100!$ have when written in base $12$?

**Answer:** 48  
**Crux:** Base 12 = 2^2*3; zeros = min(floor(v2/2), v3) via Legendre.

<details><summary>Solution</summary>

$v_2(100!)=97,\ v_3(100!)=48$; since $12=2^2\cdot3$, the answer is $\min(\lfloor97/2\rfloor,48)=48$.

</details>


---

## opus-hc-008 — Algebra  (difficulty 5.0, elegance 3)

Let $a,b,c$ be the roots of $x^3-3x-1=0$. Find $a^4+b^4+c^4$.

**Answer:** 18  
**Crux:** Newton's sums with e1=0, e2=-3, e3=1.

<details><summary>Solution</summary>

$p_2=6,\ p_3=3,\ p_4=e_1p_3-e_2p_2+e_3p_1=18$.

</details>


---

## opus-hc-009 — Number Theory  (difficulty 5.0, elegance 4)

How many integers $n$ with $1\le n\le 2025$ have a base-$3$ representation using only the digits $0$ and $1$?

**Answer:** 127  
**Crux:** Such n are sums of distinct powers of 3.

<details><summary>Solution</summary>

Powers $3^0,\dots,3^6$ suffice ($3^7=2187>2025$), and every subset sums to at most $1093\le2025$. The $2^7-1=127$ nonempty subsets give $127$ values.

</details>


---

## opus-hc-010 — Combinatorics  (difficulty 5.0, elegance 4)

How many subsets of $\{1,2,\dots,12\}$ contain no two consecutive integers?

**Answer:** 377  
**Crux:** Count g(n)=g(n-1)+g(n-2)=F(n+2).

<details><summary>Solution</summary>

Conditioning on whether $n$ is used gives $g(n)=g(n-1)+g(n-2)$, so $g(n)=F_{n+2}$; $g(12)=F_{14}=377$.

</details>


---

## opus-hc-011 — Number Theory  (difficulty 5.5, elegance 4)

Find the remainder when $2^{2025}$ is divided by $1000$.

**Answer:** 432  
**Crux:** Split mod 8 and mod 125 (CRT); ord(2) | 100 mod 125.

<details><summary>Solution</summary>

$2^{2025}\equiv0\pmod8$; mod $125$, $2^{100}\equiv1$ so $2^{2025}\equiv2^{25}\equiv57$. CRT gives $432$.

</details>


---

## opus-hc-012 — Algebra  (difficulty 4.5, elegance 4)

How many ordered pairs $(x,y)$ of positive integers satisfy $\dfrac1x+\dfrac1y=\dfrac1{12}$?

**Answer:** 15  
**Crux:** (x-12)(y-12)=144; solutions correspond to positive divisors of 144.

<details><summary>Solution</summary>

Clearing denominators, $(x-12)(y-12)=144$. Each of the $d(144)=15$ positive divisors of $144=2^4\cdot3^2$ gives one ordered pair. Answer $15$.

</details>


---

## opus-hc-013 — Combinatorics  (difficulty 5.5, elegance 4)

How many distinct ways are there to color the $6$ beads of a bracelet with $2$ colors, treating colorings that differ by a rotation as the same? (Reflections are not allowed.)

**Answer:** 14  
**Crux:** Burnside over the 6 rotations: (1/6) sum 2^gcd(k,6).

<details><summary>Solution</summary>

$\frac16\bigl(2^6+2^1+2^2+2^3+2^2+2^1\bigr)=\frac{84}{6}=14$.

</details>


---

## opus-hc-014 — Geometry  (difficulty 4.0, elegance 3)

Triangle $ABC$ has $AB=13$, $BC=14$, $CA=15$. Find $100$ times the inradius of the triangle.

**Answer:** 400  
**Crux:** r = Area/s; Heron gives area 84, s=21.

<details><summary>Solution</summary>

Heron gives area $84$ and $s=21$, so $r=84/21=4$ and $100r=400$.

</details>


---

## opus-hc-015 — Number Theory  (difficulty 6.0, elegance 2)

For how many integers $n$ with $1\le n\le 2025$ do $n$ and $n+1$ have the same number of positive divisors?

**Answer:** 243  
**Crux:** Compare d(n) and d(n+1) across the range.

<details><summary>Solution</summary>

Direct computation of $d(n)$ shows exactly $243$ values of $n\le2025$ satisfy $d(n)=d(n+1)$.

</details>


---

## opus-hc-016 — Combinatorics  (difficulty 5.0, elegance 3)

Three fair six-sided dice are rolled. The expected value of the largest number shown is $\frac{m}{n}$ in lowest terms. Find $m+n$.

**Answer:** 143  
**Crux:** E[max] = sum_{k=1}^6 P(max >= k) = sum (1 - ((k-1)/6)^3).

<details><summary>Solution</summary>

$E[\max]=\sum_{k=1}^{6}\Bigl(1-\bigl(\tfrac{k-1}{6}\bigr)^3\Bigr)=\frac{119}{24}$, so $m+n=143$.

</details>


---
