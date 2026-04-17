---
layout: page
title: "Sofie Goethals"
subtitle: "Assistant Professor · University of Antwerp"
---

<div class="profile-hero">
  <img src="/assets/img/Sofie Goethals-5.jpg" alt="Sofie Goethals" />
  <div class="profile-hero-text">
    <p>
      I am an Assistant Professor at the <strong>University of Antwerp</strong>, where I study how to make AI systems more aligned with our ethical objectives. My research spans <strong>Trustworthy Machine Learning</strong>, <strong>Explainable AI</strong>, and <strong>Computational Social Science</strong>.
    </p>
    <p>
      Previously I was a postdoctoral researcher at <strong>Columbia Business School</strong> (FWO/BAEF/Fulbright fellow) and completed my PhD in the <a href="https://admantwerp.github.io/">Applied Data Mining group</a> at the University of Antwerp under Professor David Martens.
    </p>
    <div class="research-tags">
      <span class="research-tag"><i class="fas fa-balance-scale"></i> Fairness</span>
      <span class="research-tag"><i class="fas fa-search"></i> Explainability</span>
      <span class="research-tag"><i class="fas fa-lock"></i> Privacy</span>
      <span class="research-tag"><i class="fas fa-robot"></i> Large Language Models</span>
      <span class="research-tag"><i class="fas fa-users"></i> Computational Social Science</span>
    </div>
  </div>
</div>

---

### 🔊 Recent News

{% assign recent_news = site.data.news | slice: 0, 5 %}
<ul class="news-list">
{% for item in recent_news %}
<li><span class="news-date">{{ item.date }}</span> {{ item.emoji }} {{ item.text }}</li>
{% endfor %}
</ul>

<a href="/content/news" style="font-size:0.9rem; font-weight:600;">See all news →</a>
