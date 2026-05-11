/* =========================================================================
   Palimpsest NYC — site interactions
   - sticky nav shadow on scroll
   - hero atlas SSE-stream simulation (types out event-by-event)
   - chat demo population
   - number count-up on viewport enter
   ========================================================================= */

(function () {
  'use strict';

  // -------------------- Nav scroll shadow --------------------
  const nav = document.getElementById('nav');
  if (nav) {
    const onScroll = () => {
      if (window.scrollY > 8) nav.classList.add('is-scrolled');
      else nav.classList.remove('is-scrolled');
    };
    document.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // -------------------- Hero atlas event stream --------------------
  const streamEl = document.getElementById('atlasStream');
  if (streamEl) {
    const events = [
      { ev: 'tool_call',   text: 'search_places(bbox=[-73.985,40.795,-73.945,40.825], k=8)' },
      { ev: 'tool_result', text: '8 places · 0.87 mean cosine · 14ms' },
      { ev: 'tool_call',   text: 'plan_walk(stops=4, max_dist=1.6km)' },
      { ev: 'tool_result', text: 'Riverside → Low → Cathedral → Morningside · 1.42km · 22min' },
      { ev: 'narration',   text: '"Built between 1927 and 1930, Riverside Church..."' },
      { ev: 'citation',    text: '{ doc_id: "wp:Riverside_Church", paragraph: 3, score: 0.871 }' },
      { ev: 'walk',        text: 'flyTo(stop=1, ease=ease-in-out, duration=2000)' },
      { ev: 'done',        text: 'ok · 4 stops cited · contract pass' }
    ];

    let i = 0;
    const writeNext = () => {
      if (i >= events.length) {
        // restart loop after a beat
        setTimeout(() => {
          streamEl.innerHTML = '';
          i = 0;
          writeNext();
        }, 4500);
        return;
      }
      const e = events[i++];
      const line = document.createElement('span');
      line.className = 'line event-' + e.ev;
      line.innerHTML =
        '<span class="v">→ </span>' +
        '<span class="k">' + e.ev + '</span> ' +
        '<span class="s">' + escapeHtml(e.text) + '</span>';
      streamEl.appendChild(line);

      // keep the stream pinned to its viewable rows (drop older lines once we overflow)
      while (streamEl.children.length > 7) streamEl.removeChild(streamEl.firstChild);

      setTimeout(writeNext, 520 + Math.random() * 220);
    };

    // kick off slightly delayed so the map animation lands first
    setTimeout(writeNext, 800);
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
  }

  // -------------------- Chat demo --------------------
  const chatBody = document.getElementById('chatBody');
  if (chatBody) {
    const conversation = [
      {
        kind: 'user',
        html: 'Take me on a walk near Columbia. I like history and quiet streets.'
      },
      {
        kind: 'tool',
        html: '<span class="name">search_places</span><span class="arrow"> → </span><span class="result">8 results · k=8 · ms=14</span>'
      },
      {
        kind: 'agent',
        html: '<em>A short walk through Morningside Heights.</em><br><br>' +
              'We start at <strong>Riverside Church</strong> &mdash; a Gothic ' +
              'limestone tower completed in 1930, funded by John D. Rockefeller&nbsp;Jr.' +
              '<span class="ref wiki">wiki·p3</span>'
      },
      {
        kind: 'tool',
        html: '<span class="name">plan_walk</span><span class="arrow"> → </span><span class="result">4 stops · 1.42km · 22min</span>'
      },
      {
        kind: 'agent',
        html: 'Walk east two blocks to <strong>Low Library</strong>, the ' +
              'Beaux-Arts centerpiece of Columbia\u2019s Morningside campus.' +
              '<span class="ref wiki">wiki·p1</span>' +
              '<span class="ref osm">osm·way</span>'
      },
      {
        kind: 'agent',
        html: 'Then south to the <strong>Cathedral of Saint John the Divine</strong>, ' +
              'still unfinished after a century of work.<span class="ref wiki">wiki·p2</span>'
      },
      {
        kind: 'user',
        html: 'How long does the whole thing take?'
      },
      {
        kind: 'agent',
        html: '<em>About twenty-two minutes at a steady pace.</em> If you want, ' +
              'I can add Morningside Park as a final stop &mdash; another four minutes east.'
      }
    ];

    // Render with a stagger so it feels live.
    conversation.forEach((msg, idx) => {
      setTimeout(() => {
        const row = document.createElement('div');
        row.className = 'msg ' + msg.kind;
        row.innerHTML = '<div class="bubble">' + msg.html + '</div>';
        chatBody.appendChild(row);
        chatBody.scrollTop = chatBody.scrollHeight;
      }, idx * 380);
    });
  }

  // -------------------- Number count-up on intersect --------------------
  const bignums = document.querySelectorAll('.bignum[data-count]');
  if ('IntersectionObserver' in window && bignums.length) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        if (el.dataset.animated) return;
        el.dataset.animated = '1';
        const target = parseInt(el.dataset.count, 10);
        const suffix = el.innerHTML.includes('%') ? '<span style="font-size:0.45em;color:var(--plum);">%</span>' : '';
        const isPct = el.innerHTML.includes('%');
        const duration = 1200;
        const start = performance.now();
        const tick = (t) => {
          const p = Math.min(1, (t - start) / duration);
          const eased = 1 - Math.pow(1 - p, 3);
          const v = Math.round(target * eased);
          el.innerHTML = v + suffix;
          if (p < 1) requestAnimationFrame(tick);
          else el.innerHTML = target + suffix;
        };
        requestAnimationFrame(tick);
        io.unobserve(el);
      });
    }, { threshold: 0.4 });
    bignums.forEach((b) => io.observe(b));
  }

  // -------------------- Reveal-on-scroll for cards (subtle) --------------------
  if ('IntersectionObserver' in window) {
    const reveal = document.querySelectorAll('.arch-card, .source-card, .team-card, .num-block');
    reveal.forEach((el) => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(8px)';
      el.style.transition = 'opacity 500ms ease, transform 500ms ease';
    });
    const io2 = new IntersectionObserver((entries) => {
      entries.forEach((entry, i) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        setTimeout(() => {
          el.style.opacity = '';
          el.style.transform = '';
        }, i * 60);
        io2.unobserve(el);
      });
    }, { threshold: 0.15 });
    reveal.forEach((el) => io2.observe(el));
  }

})();
