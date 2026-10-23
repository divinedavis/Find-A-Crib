/* Building chat on findacrib.com (owner, 2026-10-19: "build chat on the web
 * too", with typing bubbles). The web twin of the app's BuildingChat +
 * BuildingChatView: same tables (db/0063, db/0067), same encryption
 * (chat-crypto.js), same rules (terms before joining, report, block, a
 * client-side filter because the server only sees ciphertext).
 *
 *   FacBuildingChat.open({ bbl, address, client })   // client = supabase-js
 *
 * Everything people typed is put on the page with textContent, never HTML.
 *
 * Instagram's direct-message layout (owner, 2026-10-23, from a screen
 * recording), in Find A Crib's colours, the same as the app: yours on the
 * right, neighbors' on the left; centred time lines; hold (or right-click)
 * a bubble for reactions + Reply / Copy / Details / Delete for you / Unsend;
 * double-click hearts it; swipe right on a phone to reply, left for times.
 * Reactions and reply quotes ride inside the sealed payload (k/to/e, r).
 */
(function () {
  'use strict';
  var C = window.FacChatCrypto;
  var TYPING_EVERY = 2500, TYPING_SHOWN = 5000, RUN_GAP = 5 * 60 * 1000, STAMP_GAP = 60 * 60 * 1000;
  var QUICK = ['❤️', '😂', '😮', '😢', '🔥', '👍'];                       // = BuildingChat.quickReactions
  var MORE = ['🙏', '👏', '💯', '😍', '🎉', '😡', '🤔', '👀', '🙌', '😅', '🫶', '👎'];
  var BLOCKED_WORDS = ['nigger', 'nigga', 'faggot', 'fag', 'kike', 'spic', 'chink', 'tranny', 'retard',
                       'kill yourself', 'kys', 'i will kill you', "i'll kill you"];   // = ChatFilter in BuildingChat.swift
  var REPORT_REASONS = ['Harassment or hate', 'Threat or violence', 'Spam or scam', 'Something else'];

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'on') for (var e in attrs.on) n.addEventListener(e, attrs.on[e]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) n.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function track(name, props) { try { window.facTrack && window.facTrack(name, props); } catch (e) {} }

  function blocks(text) {
    var t = ' ' + text.toLowerCase().replace(/[^a-z' ]/g, ' ') + ' ';
    return BLOCKED_WORDS.some(function (w) { return t.indexOf(' ' + w + ' ') >= 0; });
  }

  /* ---- layout rules (exported for tests) ---- */
  function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
  /* Instagram's time lines, as ChatLayout.stamp in the app. */
  function stamp(d, now) {
    now = now || new Date();
    var time = clock(d);
    if (sameDay(d, now)) return 'Today ' + time;
    var y = new Date(now); y.setDate(y.getDate() - 1);
    if (sameDay(d, y)) return 'Yesterday ' + time;
    var week = new Date(now); week.setHours(0, 0, 0, 0); week.setDate(week.getDate() - 6);
    if (d >= week) return d.toLocaleDateString('en-US', { weekday: 'short' }) + ' ' + time;
    var o = d.getFullYear() === now.getFullYear() ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' };
    return d.toLocaleDateString('en-US', o) + ' at ' + time;
  }
  /* A sender's messages within 5 minutes stack as one run; a new day or an
     hour's gap gets a centred time line. */
  function runs(ms, now) {
    var out = [], cur = null, prev = null;
    ms.forEach(function (m) {
      var label = null;
      if (!prev || !sameDay(prev.at, m.at) || m.at - prev.at >= STAMP_GAP) { label = stamp(m.at, now); cur = null; }
      if (!cur || cur.sender !== m.sender || m.at - cur.messages[cur.messages.length - 1].at > RUN_GAP) {
        cur = { sender: m.sender, mine: m.mine, messages: [], stamp: label }; out.push(cur);
      }
      cur.messages.push(m); prev = m;
    });
    return out;
  }
  /* One emoji and nothing else, so a reaction can't carry a sentence. */
  function isReaction(e) {
    if (typeof e !== 'string' || !e || e.length > 16) return false;
    var n = window.Intl && Intl.Segmenter ? Array.from(new Intl.Segmenter().segment(e)).length : Array.from(e).length;
    return n === 1 && /\p{Extended_Pictographic}/u.test(e);
  }
  function initials(name) {
    var w = (name || '').split(/[^\p{L}\p{N}]+/u).filter(Boolean).slice(0, 2);
    return w.map(function (x) { return x[0]; }).join('').toUpperCase() || '•';
  }
  function typingLine(names) {
    if (!names.length) return '';
    if (names.length === 1) return names[0] + ' is typing…';
    if (names.length === 2) return names[0] + ' and ' + names[1] + ' are typing…';
    return names.length + ' neighbors are typing…';
  }
  function clock(d) { return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }); }
  function hiddenKey(bbl) { return 'fac.chat.hidden.' + bbl; }

  /* ---- the chat ---- */
  function open(opts) {
    var sb = opts.client, bbl = opts.bbl, address = opts.address || 'your building';
    var state = { me: null, myKey: null, ident: null, keys: {}, messages: [], reactions: [], blocked: {}, joined: false,
                  members: 0, typers: {}, lastTyping: 0, detail: null, ch: null, typingCh: null, timer: null,
                  hidden: {}, replyTo: null, menu: null };
    try { (JSON.parse(localStorage.getItem(hiddenKey(bbl)) || '[]') || []).forEach(function (id) { state.hidden[id] = true; }); } catch (e) {}

    var root = el('div', { class: 'fc-chat', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Building chat', 'data-testid': 'chat-sheet' });
    var back = el('div', { class: 'fc-chat-backdrop' }, [root]);
    var closeBtn = el('button', { class: 'fc-chat-x', type: 'button', text: 'Close', on: { click: close } });
    var leaveBtn = el('button', { class: 'fc-chat-x', type: 'button', text: 'Leave', hidden: true, 'data-testid': 'chat-leave', on: { click: leave } });
    root.appendChild(el('div', { class: 'fc-chat-head' }, [closeBtn, el('h2', { text: 'Building chat · ' + address }), leaveBtn]));
    var body = el('div', { class: 'fc-chat-body' });
    root.appendChild(body);
    document.body.appendChild(back);
    var prevOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
    document.addEventListener('keydown', onKey);
    function onKey(e) {
      if (e.key !== 'Escape') return;
      if (state.menu) closeMenu(); else if (state.detail) showDetail(null); else if (state.replyTo) setReply(null); else close();
    }

    function close() {
      stopLive(); document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow; back.remove();
    }
    function setBody(node) { body.textContent = ''; body.appendChild(node); }
    function lockLine() { return el('span', { class: 'fc-lock', text: '🔒 End-to-end encrypted' }); }
    function fail(text) { setBody(el('div', { class: 'fc-card' }, [el('p', { class: 'err', text: text })])); }

    function start() {
      setBody(el('div', { class: 'fc-card' }, [el('p', { text: 'Loading…' })]));
      C.supported().then(function (ok) {
        if (!ok) return fail('This browser can’t do encrypted chat. Update it, or use the Find A Crib iPhone app.');
        return sb.auth.getSession().then(function (r) {
          var sess = r && r.data && r.data.session;
          if (!sess) return signedOut();
          state.me = sess.user.id.toLowerCase();
          try { sb.realtime.setAuth(sess.access_token); } catch (e) {}
          return C.identity().then(function (id) {
            state.ident = id; state.myKey = state.me + ':' + id.deviceId;
            return sb.from('chat_members').select('user_id').eq('bbl', bbl).eq('user_id', state.me);
          }).then(function (r) {
            if (r.error) throw r.error;
            state.joined = r.data.length > 0;
            if (!state.joined) return joinCard();
            return publishDevice().then(refresh).then(function () { room(); goLive(); });
          });
        });
      }).catch(function () { fail('Couldn’t reach the chat. Close it and try again.'); });
    }

    function signedOut() {
      setBody(el('div', { class: 'fc-card' }, [
        lockLine(),
        el('h3', { text: 'Talk with the people in ' + address }),
        el('p', { text: 'Sign in to join your building’s chat. Messages are end-to-end encrypted: only the people in the chat can read them.' }),
        el('a', { class: 'btn', href: '/?auth=signup&next=' + encodeURIComponent('/casa/?bbl=' + bbl + '&chat=1'), 'data-testid': 'chat-signin', text: 'Sign in to chat' })
      ]));
    }

    function joinCard() {
      var name = el('input', { type: 'text', maxlength: '40', placeholder: 'e.g. Maria, 4B', 'data-testid': 'chat-name', autocomplete: 'nickname' });
      try { name.value = localStorage.getItem('fac.chat.name') || ''; } catch (e) {}
      var agree = el('input', { type: 'checkbox', 'data-testid': 'chat-terms' });
      var join = el('button', { class: 'btn', type: 'button', text: 'Join the chat', 'data-testid': 'chat-join', disabled: true });
      var err = el('p', { class: 'err', hidden: true });
      function check() { join.disabled = !(agree.checked && name.value.trim()); }
      name.addEventListener('input', check); agree.addEventListener('change', check); check();
      join.addEventListener('click', function () {
        join.disabled = true;
        try { localStorage.setItem('fac.chat.name', name.value.trim()); } catch (e) {}
        publishDevice().then(function () {
          return sb.from('chat_members').upsert({ bbl: bbl, user_id: state.me, agreed_terms_at: new Date().toISOString() },
                                                 { onConflict: 'bbl,user_id', ignoreDuplicates: true });
        }).then(function (r) {
          if (r.error) throw r.error;
          state.joined = true; track('chat_join', { bbl: bbl, web: true });
          return refresh().then(function () { room(); goLive(); });
        }).catch(function () { err.textContent = 'Couldn’t join the chat. Try again.'; err.hidden = false; check(); });
      });
      setBody(el('div', { class: 'fc-card' }, [
        lockLine(),
        el('h3', { text: 'Talk with the people in ' + address }),
        el('p', { text: 'Messages are end-to-end encrypted: only the people in this chat can read them — not Find A Crib, not your landlord. You’ll see messages sent after you join on this browser.' }),
        el('label', { class: 'fc-field', text: 'Your name in the chat' }), name,
        el('label', { class: 'fc-terms' }, [agree, el('span', { text: 'I’ll be respectful. No harassment, hate, threats, spam or sharing people’s private details. Find A Crib removes anyone who breaks these rules.' })]),
        join, err
      ]));
    }

    function publishDevice() {
      return sb.from('chat_devices').upsert({ user_id: state.me, device_id: state.ident.deviceId, public_key: state.ident.publicKey,
                                              updated_at: new Date().toISOString() }, { onConflict: 'user_id,device_id' })
        .then(function (r) { if (r.error) throw r.error; });
    }

    /* Members' phone + browser keys, blocks, then the last 100 messages. */
    function refresh() {
      return sb.from('chat_members').select('user_id').eq('bbl', bbl).then(function (r) {
        if (r.error) throw r.error;
        var ids = r.data.map(function (x) { return x.user_id; });
        state.members = ids.length;
        if (!ids.length) return;
        return Promise.all([
          sb.from('chat_keys').select('user_id,public_key').in('user_id', ids),
          sb.from('chat_devices').select('user_id,device_id,public_key').in('user_id', ids),
          sb.from('chat_blocks').select('blocked')
        ]).then(function (rs) {
          var k = {};
          (rs[0].data || []).forEach(function (x) { k[x.user_id.toLowerCase()] = x.public_key; });
          (rs[1].data || []).forEach(function (x) { k[x.user_id.toLowerCase() + ':' + x.device_id] = x.public_key; });
          state.keys = k; state.blocked = {};
          (rs[2].data || []).forEach(function (x) { state.blocked[x.blocked.toLowerCase()] = true; });
        });
      }).then(function () {
        return sb.from('chat_messages').select('*').eq('bbl', bbl).order('id', { ascending: false }).limit(150);
      }).then(function (r) {
        if (r.error) throw r.error;
        return Promise.all(r.data.reverse().map(decode)).then(function (ms) {
          state.messages = []; state.reactions = [];
          ms.forEach(take);
        });
      });
    }

    function senderKeyId(row) { var s = row.sender.toLowerCase(); return row.sender_device ? s + ':' + row.sender_device : s; }

    function decode(row) {
      var sender = row.sender.toLowerCase();
      var m = { id: row.id, sender: sender, name: 'Neighbor', text: null, at: new Date(row.created_at), mine: sender === state.me,
                fromWeb: !!row.sender_device, reply: null, react: null };
      var pub = state.keys[senderKeyId(row)];
      if (!pub) return Promise.resolve(m);
      return C.open({ salt: row.salt, ciphertext: row.ciphertext, keys: row.keys }, bbl, state.myKey, state.ident.privateKey, pub)
        .then(function (bytes) {
          var p = JSON.parse(new TextDecoder().decode(bytes));
          if (typeof p.t === 'string') m.text = p.t;
          if (typeof p.n === 'string' && p.n) m.name = p.n.slice(0, 40);
          if (p.k === 'react' && typeof p.to === 'number' && isReaction(p.e)) m.react = { to: p.to, emoji: p.e };
          if (p.r && typeof p.r.id === 'number' && typeof p.r.t === 'string')
            m.reply = { id: p.r.id, n: String(p.r.n || '').slice(0, 40), t: p.r.t.slice(0, 160) };
          return m;
        }, function () { return m; });
    }

    /* A decoded row is either a message or a reaction on one. */
    function take(m) {
      if (m.react) {
        // The newest from each person on a message wins.
        var old = state.reactions.filter(function (x) { return x.sender === m.sender && x.to === m.react.to; })[0];
        if (old && old.id > m.id) return;
        if (old) state.reactions.splice(state.reactions.indexOf(old), 1);
        state.reactions.push({ id: m.id, to: m.react.to, sender: m.sender, name: m.name, emoji: m.react.emoji, mine: m.mine });
        return;
      }
      if (!state.messages.some(function (x) { return x.id === m.id; })) state.messages.push(m);
    }
    function reactionsOn(id) {
      return state.reactions.filter(function (x) { return x.to === id && !state.blocked[x.sender]; });
    }
    /* A row is gone: an unsent message or a taken-back reaction. */
    function removed(id) {
      state.messages = state.messages.filter(function (m) { return m.id !== id; });
      state.reactions = state.reactions.filter(function (x) { return x.id !== id; });
      if (state.replyTo && state.replyTo.id === id) setReply(null);
    }

    /* ---- the room ---- */
    var scroll, col, typingBox, composer, input, sendBtn, errLine, detail, barCount, replyBar, jump, roomEl;
    function room() {
      leaveBtn.hidden = false;
      barCount = el('span');
      scroll = el('div', { class: 'fc-scroll' });
      col = el('div', { class: 'fc-col' });
      scroll.appendChild(col);
      input = el('textarea', { rows: '1', maxlength: '2000', placeholder: 'Message...', 'aria-label': 'Message', 'data-testid': 'chat-input' });
      sendBtn = el('button', { class: 'fc-send', type: 'button', 'aria-label': 'Send', 'data-testid': 'chat-send', hidden: true, text: '↑' });
      errLine = el('div', { class: 'fc-err', hidden: true });
      replyBar = el('div', { class: 'fc-replying', hidden: true, 'data-testid': 'chat-replying' });
      composer = el('div', { class: 'fc-compose' }, [el('div', { class: 'fc-field-wrap' }, [input, sendBtn])]);
      jump = el('button', { class: 'fc-jump', type: 'button', hidden: true, 'aria-label': 'Jump to the newest message', 'data-testid': 'chat-jump', text: '↓',
                            on: { click: function () { scroll.scrollTo({ top: scroll.scrollHeight, behavior: 'smooth' }); } } });
      detail = el('aside', { class: 'fc-detail', hidden: true, 'aria-label': 'Message details', 'data-testid': 'chat-detail' });
      roomEl = el('div', { class: 'fc-room' }, [
        el('div', { class: 'fc-chat-bar' }, [lockLine(), barCount]), scroll, jump, errLine, replyBar, composer]);
      setBody(el('div', { class: 'fc-chat-body', style: 'flex:1;min-height:0;position:relative' }, [roomEl, detail]));
      input.addEventListener('input', function () {
        input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 140) + 'px';
        sendBtn.hidden = !input.value.trim();
        typed(input.value);
      });
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
      sendBtn.addEventListener('click', send);
      scroll.addEventListener('scroll', function () { jump.hidden = nearBottom(); });
      swipes();
      render(true);
      input.focus();
    }

    function nearBottom() { return scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 80; }
    function visible() { return state.messages.filter(function (m) { return !state.blocked[m.sender] && !state.hidden[m.id]; }); }
    function byId(id) { return state.messages.filter(function (m) { return m.id === id; })[0]; }

    function render(toBottom) {
      if (!col) return;
      var stay = toBottom || nearBottom();
      barCount.textContent = state.members === 1 ? 'Just you so far' : state.members + ' neighbors';
      col.textContent = '';
      var ms = visible();
      if (!ms.length) col.appendChild(el('p', { class: 'fc-empty', 'data-testid': 'chat-empty', text: 'No messages yet. Say hello to your neighbors.' }));
      runs(ms).forEach(function (run) {
        if (run.stamp) col.appendChild(el('div', { class: 'fc-stamp', 'data-testid': 'chat-stamp', role: 'separator', text: run.stamp }));
        var first = run.messages[0];
        var box = el('div', { class: 'fc-run' + (first.mine ? ' mine' : '') });
        if (!first.mine && !first.reply) box.appendChild(el('div', { class: 'fc-who', text: first.name }));
        run.messages.forEach(function (m, i) {
          box.appendChild(row(m, i === 0 && !m.reply, i === run.messages.length - 1));
        });
        col.appendChild(box);
      });
      typingBox = null;
      var names = typingNames();
      if (names.length) {
        typingBox = el('div', { class: 'fc-typing', 'data-testid': 'chat-typing' }, [
          el('span', { class: 'fc-av', 'aria-hidden': 'true', text: initials(names[0]) }),
          el('div', null, [
            el('span', { class: 'fc-dots', 'aria-hidden': 'true' }, [el('i'), el('i'), el('i')]),
            el('div', { class: 'fc-typing-line', text: typingLine(names) })])
        ]);
        col.appendChild(typingBox);
      }
      if (stay) scroll.scrollTop = scroll.scrollHeight;
      jump.hidden = nearBottom();
    }

    /* One message: quote, bubble, reactions; initials beside a neighbor's
       last bubble; hover tools; the time it slides out to. */
    function row(m, first, last) {
      var r = el('div', { class: 'fc-row' + (m.mine ? ' mine' : ''), 'data-id': String(m.id) });
      if (!m.mine) r.appendChild(last ? el('span', { class: 'fc-av', 'aria-hidden': 'true', text: initials(m.name) }) : el('span', { class: 'fc-av-gap' }));
      var stack = el('div', { class: 'fc-stack' });
      if (m.reply) stack.appendChild(quote(m));
      var b = el('button', { type: 'button', class: 'fc-msg' + (m.text === null ? ' locked' : '') + (first ? ' first' : '') + (last ? ' last' : ''),
                             'data-testid': 'chat-message', 'aria-haspopup': 'menu',
                             'aria-current': state.detail && state.detail.id === m.id ? 'true' : null,
                             text: m.text === null ? 'Sent before this browser joined, so it can’t be read here' : m.text });
      b.addEventListener('click', function (e) { if (e.detail === 0) openMenu(m, b); });   // keyboard Enter/Space
      b.addEventListener('dblclick', function (e) { e.preventDefault(); if (m.text !== null) react(m, '❤️'); });
      b.addEventListener('contextmenu', function (e) { e.preventDefault(); openMenu(m, b); });
      holdToOpen(b, m);
      stack.appendChild(b);
      var rs = reactionsOn(m.id);
      if (rs.length) {
        var seen = {}, faces = rs.map(function (x) { return x.emoji; }).filter(function (x) { return seen[x] ? false : (seen[x] = true); }).slice(0, 3);
        stack.appendChild(el('button', { type: 'button', class: 'fc-pill', 'data-testid': 'chat-reactions',
                                         'aria-label': 'Reactions: ' + rs.map(function (x) { return x.emoji; }).join(' '),
                                         on: { click: function () { showReactions(m); } } },
                             [faces.join(''), rs.length > 1 ? el('span', { text: String(rs.length) }) : null]));
      }
      r.appendChild(stack);
      if (m.text !== null) {
        r.appendChild(el('div', { class: 'fc-tools' }, [
          el('button', { type: 'button', 'aria-label': 'React', title: 'React', text: '☺', on: { click: function () { openMenu(m, b); } } }),
          el('button', { type: 'button', 'aria-label': 'Reply', title: 'Reply', 'data-testid': 'chat-tool-reply', text: '↩', on: { click: function () { setReply(m); } } }),
          el('button', { type: 'button', 'aria-label': 'More', title: 'More', 'data-testid': 'chat-tool-more', text: '⋯', on: { click: function () { openMenu(m, b); } } })
        ]));
      }
      r.appendChild(el('time', { class: 'fc-stime', 'data-testid': 'chat-time', datetime: m.at.toISOString(), text: clock(m.at) }));
      return r;
    }

    function quote(m) {
      var orig = byId(m.reply.id), to = orig && orig.mine ? 'you' : (orig ? orig.name : m.reply.n);
      var cap = m.mine ? (orig && orig.mine ? 'You replied to yourself' : 'You replied to ' + to) : 'Replied to ' + to;
      return el('div', { class: 'fc-quote', 'data-testid': 'chat-quote' }, [
        el('div', { class: 'fc-quote-cap', text: '↩ ' + cap }),
        el('button', { type: 'button', class: 'fc-quote-text', text: m.reply.t, on: { click: function () {
          var t = col.querySelector('.fc-row[data-id="' + m.reply.id + '"]');
          if (t) { t.scrollIntoView({ block: 'center', behavior: 'smooth' }); t.classList.add('flash'); setTimeout(function () { t.classList.remove('flash'); }, 900); }
        } } })
      ]);
    }

    /* Touch: hold half a second for the menu. */
    function holdToOpen(b, m) {
      var t = null;
      b.addEventListener('pointerdown', function (e) {
        if (e.pointerType !== 'touch') return;
        t = setTimeout(function () { t = null; if (navigator.vibrate) navigator.vibrate(10); openMenu(m, b); }, 450);
      });
      ['pointerup', 'pointercancel', 'pointerleave', 'pointermove'].forEach(function (ev) {
        b.addEventListener(ev, function (e) { if (ev === 'pointermove' && Math.abs(e.movementX) + Math.abs(e.movementY) < 3) return; clearTimeout(t); t = null; });
      });
    }

    /* Touch: swipe a bubble right to reply, the room left to see times. */
    function swipes() {
      var s = null;
      scroll.addEventListener('touchstart', function (e) {
        var r = e.target.closest && e.target.closest('.fc-row');
        s = { x: e.touches[0].clientX, y: e.touches[0].clientY, row: r, dx: 0, horiz: null };
      }, { passive: true });
      scroll.addEventListener('touchmove', function (e) {
        if (!s) return;
        var dx = e.touches[0].clientX - s.x, dy = e.touches[0].clientY - s.y;
        if (s.horiz === null && Math.abs(dx) + Math.abs(dy) > 10) s.horiz = Math.abs(dx) > Math.abs(dy) * 1.4;
        if (!s.horiz) return;
        s.dx = dx;
        if (dx > 0 && s.row) s.row.style.transform = 'translateX(' + Math.min(dx * 0.75, 72) + 'px)';
        else if (dx < 0) col.style.setProperty('--shift', Math.max(dx * 0.8, -64) + 'px');
      }, { passive: true });
      scroll.addEventListener('touchend', function () {
        if (!s) return;
        if (s.horiz && s.dx * 0.75 >= 56 && s.row) {
          var m = byId(+s.row.dataset.id);
          if (m && m.text !== null) { if (navigator.vibrate) navigator.vibrate(8); setReply(m); }
        }
        if (s.row) s.row.style.transform = '';
        col.style.removeProperty('--shift');
        s = null;
      });
    }

    function setReply(m) {
      state.replyTo = m;
      if (!replyBar) return;
      replyBar.textContent = '';
      replyBar.hidden = !m;
      if (!m) return;
      replyBar.appendChild(el('div', { class: 'fc-replying-text' }, [
        el('strong', { text: m.mine ? 'Replying to yourself' : 'Replying to ' + m.name }),
        el('span', { text: m.text || '' })]));
      replyBar.appendChild(el('button', { type: 'button', class: 'fc-replying-x', 'aria-label': 'Cancel reply', 'data-testid': 'chat-reply-cancel', text: '✕',
                                          on: { click: function () { setReply(null); } } }));
      input.focus();
    }

    /* Instagram's hold menu: the room blurs; reactions above the bubble,
       actions below it. */
    function openMenu(m, b) {
      closeMenu();
      var rect = b.getBoundingClientRect(), base = root.getBoundingClientRect();
      var mineNow = reactionsOn(m.id).filter(function (x) { return x.mine; })[0];
      var back = el('div', { class: 'fc-menu-back', 'data-testid': 'chat-hold-menu' });
      var menu = el('div', { class: 'fc-menu' + (m.mine ? ' mine' : ''), role: 'menu', 'aria-label': 'Message actions' });
      var more = el('div', { class: 'fc-emoji-more', hidden: true });
      function face(e) {
        return el('button', { type: 'button', role: 'menuitem', class: mineNow && mineNow.emoji === e ? 'on' : null,
                              'aria-label': (mineNow && mineNow.emoji === e ? 'Remove ' : 'React ') + e, 'data-testid': 'chat-react-' + e, text: e,
                              on: { click: function () { closeMenu(); react(m, e); } } });
      }
      if (m.text !== null) {
        var bar = el('div', { class: 'fc-emoji' }, QUICK.map(face).concat([
          el('button', { type: 'button', class: 'plus', 'aria-label': 'More reactions', 'data-testid': 'chat-react-more', text: '+',
                         on: { click: function () { more.hidden = !more.hidden; } } })]));
        MORE.forEach(function (e) { more.appendChild(face(e)); });
        menu.appendChild(bar); menu.appendChild(more);
      }
      menu.appendChild(el('div', { class: 'fc-menu-bubble' + (m.mine && m.text !== null ? ' mine' : ''), text: m.text === null ? 'Sent before this browser joined' : m.text }));
      var list = el('div', { class: 'fc-menu-list' }, [el('div', { class: 'fc-menu-time', text: stamp(m.at).toUpperCase() })]);
      function item(label, id, fn, danger) {
        list.appendChild(el('button', { type: 'button', role: 'menuitem', class: danger ? 'danger' : null, 'data-testid': id, text: label,
                                        on: { click: function () { closeMenu(); fn(); } } }));
      }
      if (m.text !== null) {
        item('Reply', 'chat-menu-reply', function () { setReply(m); });
        if (navigator.clipboard) item('Copy', 'chat-menu-copy', function () { navigator.clipboard.writeText(m.text); });
      }
      item('Details', 'chat-menu-details', function () { showDetail(m); });
      item('Delete for you', 'chat-menu-delete', function () { hideForMe(m); });
      if (m.mine) item('Unsend', 'chat-menu-unsend', function () { unsend(m); }, true);
      else {
        item('Report', 'chat-menu-report', function () { showDetail(m); reportFlow(m); }, true);
        item('Block ' + m.name, 'chat-menu-block', function () { block(m); }, true);
      }
      menu.appendChild(list);
      back.appendChild(menu);
      back.addEventListener('click', function (e) { if (e.target === back) closeMenu(); });
      root.appendChild(back);
      // Sit the bubble copy where the bubble was, kept on screen.
      var top = rect.top - base.top - 60, h = menu.offsetHeight;
      top = Math.max(12, Math.min(top, base.height - h - 12));
      menu.style.top = top + 'px';
      if (m.mine) menu.style.right = Math.max(12, base.right - rect.right) + 'px';
      else menu.style.left = Math.max(12, rect.left - base.left) + 'px';
      state.menu = back;
      var firstBtn = menu.querySelector('button'); if (firstBtn) firstBtn.focus();
    }
    function closeMenu() { if (state.menu) { state.menu.remove(); state.menu = null; } }

    function showReactions(m) {
      state.detail = m;
      detail.textContent = '';
      detail.appendChild(el('button', { class: 'fc-chat-x fc-detail-close', type: 'button', text: 'Done', on: { click: function () { showDetail(null); } } }));
      detail.appendChild(el('h3', { text: 'Reactions' }));
      var ul = el('ul', { class: 'fc-reaction-list', 'data-testid': 'chat-reaction-list' });
      reactionsOn(m.id).forEach(function (x) {
        ul.appendChild(el('li', null, [
          el('span', { class: 'fc-av', 'aria-hidden': 'true', text: initials(x.name) }),
          el('span', { class: 'who', text: x.mine ? 'You' : x.name }),
          x.mine ? el('button', { type: 'button', text: 'Remove', on: { click: function () { react(m, x.emoji); showDetail(null); } } }) : null,
          el('span', { class: 'face', text: x.emoji })]));
      });
      detail.appendChild(ul);
      detail.hidden = false;
      render();
    }

    /* REVEAL: the detail is a sheet on narrow chats and a side panel on wide
       ones — chat.css decides by the chat's own width (@container). */
    function showDetail(m) {
      state.detail = m;
      detail.textContent = '';
      detail.appendChild(el('p', { class: 'fc-detail-hint', text: 'Hold or right-click a message to react, reply or see its details.' }));
      if (!m) { detail.hidden = true; render(); return; }
      detail.appendChild(el('button', { class: 'fc-chat-x fc-detail-close', type: 'button', text: 'Done', on: { click: function () { showDetail(null); } } }));
      detail.appendChild(el('h3', { text: m.mine ? 'You' : m.name }));
      detail.appendChild(el('p', { class: 'fc-text', text: m.text === null
        ? 'This browser joined after the message was sent, or it was sent to an older key. Only devices in the chat at the time can read it.' : m.text }));
      detail.appendChild(el('dl', null, [
        el('dt', { text: 'Sent' }), el('dd', { text: m.at.toLocaleString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) }),
        el('dt', { text: 'From' }), el('dd', { text: m.fromWeb ? 'findacrib.com' : 'iPhone app' }),
        el('dt', { text: 'Privacy' }), el('dd', { text: 'End-to-end encrypted' })
      ]));
      var acts = el('div', { class: 'fc-actions' });
      if (m.text !== null && navigator.clipboard) acts.appendChild(el('button', { type: 'button', text: 'Copy', on: { click: function () { navigator.clipboard.writeText(m.text); } } }));
      if (!m.mine) {
        acts.appendChild(el('button', { type: 'button', 'data-testid': 'chat-detail-report', text: 'Report', on: { click: function () { reportFlow(m); } } }));
        acts.appendChild(el('button', { type: 'button', class: 'danger', text: 'Block ' + m.name, on: { click: function () { block(m); } } }));
      }
      detail.appendChild(acts);
      detail.hidden = false;
      render();
    }

    function reportFlow(m) {
      var acts = detail.querySelector('.fc-actions'); acts.textContent = '';
      acts.appendChild(el('p', { class: 'muted', style: 'width:100%;margin:0', text: 'This sends the message’s text to Find A Crib to review. Messages are otherwise unreadable to us.' }));
      REPORT_REASONS.forEach(function (reason) {
        acts.appendChild(el('button', { type: 'button', text: reason, on: { click: function () {
          sb.from('chat_reports').insert({ message_id: m.id, bbl: bbl, sender: m.sender, plaintext: m.text, reason: reason }).then(function (r) {
            acts.textContent = '';
            acts.appendChild(el('p', { class: 'muted', style: 'margin:0', text: r.error ? 'Couldn’t send the report. Try again.' : 'Thanks — we’ll review it within 24 hours.' }));
          });
        } } }));
      });
    }

    function block(m) {
      sb.from('chat_blocks').insert({ blocked: m.sender }).then(function () { state.blocked[m.sender] = true; showDetail(null); });
    }

    function leave() {
      if (!confirm('Leave the chat for ' + address + '?')) return;
      sb.from('chat_members').delete().eq('bbl', bbl).eq('user_id', state.me).then(function () { stopLive(); close(); });
    }

    function myName() { try { return (localStorage.getItem('fac.chat.name') || '').slice(0, 40); } catch (e) { return ''; } }

    /* Seals a payload for every member right now and posts it. */
    function post(payload) {
      return refresh().then(function () {
        return C.seal(new TextEncoder().encode(JSON.stringify(payload)), bbl, state.ident.privateKey, state.keys);
      }).then(function (s) {
        return sb.from('chat_messages').insert({ bbl: bbl, salt: s.salt, ciphertext: s.ciphertext, keys: s.keys, sender_device: state.ident.deviceId });
      }).then(function (r) { if (r.error) throw r.error; });
    }

    function send() {
      var t = input.value.trim(), name = myName(), to = state.replyTo;
      if (!t || t.length > 2000) return;
      if (blocks(t)) return showErr('That message breaks the chat rules and wasn’t sent.');
      sendBtn.disabled = true;
      var payload = { t: t, n: name };
      if (to && to.text !== null) payload.r = { id: to.id, n: to.mine ? name : to.name, t: to.text.slice(0, 160) };
      post(payload).then(function () {
        input.value = ''; input.style.height = 'auto'; errLine.hidden = true; sendBtn.hidden = true;
        setReply(null);
        typed('');
        track('chat_send', { bbl: bbl, members: Object.keys(state.keys).length, web: true, reply: !!payload.r });
        render(true);
      }).catch(function () { showErr('Couldn’t send. Check your connection and try again.'); })
        .then(function () { sendBtn.disabled = false; });
    }

    /* Your reaction replaces your earlier one; the same emoji takes it back. */
    function react(m, e) {
      if (!isReaction(e)) return;
      var old = reactionsOn(m.id).filter(function (x) { return x.mine; })[0];
      var gone = old ? sb.from('chat_messages').delete().eq('id', old.id).then(function (r) { if (r.error) throw r.error; removed(old.id); })
                     : Promise.resolve();
      gone.then(function () {
        if (old && old.emoji === e) return render();
        return post({ t: 'Reacted ' + e + ' to a message', n: myName(), k: 'react', to: m.id, e: e }).then(function () {
          track('chat_react', { bbl: bbl, web: true }); render();
        });
      }).catch(function () { showErr('Couldn’t send. Check your connection and try again.'); });
    }

    function unsend(m) {
      sb.from('chat_messages').delete().eq('id', m.id).eq('sender', state.me).then(function (r) {
        if (r.error) return showErr('Couldn’t unsend. Check your connection and try again.');
        removed(m.id); track('chat_unsend', { bbl: bbl, web: true }); render();
      });
    }

    function hideForMe(m) {
      state.hidden[m.id] = true;
      try { localStorage.setItem(hiddenKey(bbl), JSON.stringify(Object.keys(state.hidden).map(Number).slice(-500))); } catch (e) {}
      render();
    }
    function showErr(t) { errLine.textContent = t; errLine.hidden = false; }

    /* ---- live: new messages + typing bubbles ---- */
    function goLive() {
      state.ch = sb.channel('chat-' + bbl)
        .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'chat_messages', filter: 'bbl=eq.' + bbl }, function (p) {
          var row = p.new;
          if (!row || state.messages.some(function (m) { return m.id === row.id; })) return;
          var ready = state.keys[senderKeyId(row)] ? Promise.resolve() : refresh();
          ready.then(function () { return state.messages.some(function (m) { return m.id === row.id; }) ? null : decode(row); })
            .then(function (m) { if (m) take(m); delete state.typers[row.sender.toLowerCase()]; render(); });
        })
        // Unsent messages and taken-back reactions: Realtime can't filter
        // deletes and sends only the id, so ids we don't hold are ignored.
        .on('postgres_changes', { event: 'DELETE', schema: 'public', table: 'chat_messages' }, function (p) {
          var id = p.old && p.old.id;
          if (typeof id === 'number') { removed(id); render(); }
        })
        .subscribe();
      state.typingCh = sb.channel('chat-typing:' + bbl, { config: { private: true, broadcast: { self: false } } })
        .on('broadcast', { event: 'typing' }, function (msg) {
          var p = msg && msg.payload || {}, who = typeof p.u === 'string' ? p.u.toLowerCase() : null;
          if (!who || who === state.me || state.blocked[who]) return;
          if (p.stop) delete state.typers[who]; else state.typers[who] = Date.now();
          render();
          clearTimeout(state.timer);
          state.timer = setTimeout(render, TYPING_SHOWN + 50);
        })
        .subscribe();
    }
    function stopLive() {
      clearTimeout(state.timer);
      if (state.ch) sb.removeChannel(state.ch);
      if (state.typingCh) sb.removeChannel(state.typingCh);
      state.ch = state.typingCh = null;
    }
    function typingNames() {
      var now = Date.now();
      return Object.keys(state.typers).filter(function (u) { return now - state.typers[u] < TYPING_SHOWN; })
        .sort(function (a, b) { return state.typers[a] - state.typers[b]; })
        .map(function (u) {
          for (var i = state.messages.length - 1; i >= 0; i--) {
            var m = state.messages[i]; if (m.sender === u && m.text !== null) return m.name;
          }
          return 'A neighbor';
        });
    }
    function typed(draft) {
      if (!state.typingCh) return;
      if (!draft.trim()) {
        if (!state.lastTyping) return;
        state.lastTyping = 0;
        state.typingCh.send({ type: 'broadcast', event: 'typing', payload: { u: state.me, stop: true } });
        return;
      }
      if (Date.now() - state.lastTyping < TYPING_EVERY) return;
      state.lastTyping = Date.now();
      state.typingCh.send({ type: 'broadcast', event: 'typing', payload: { u: state.me } });
    }

    start();
    return { close: close };
  }

  window.FacBuildingChat = { open: open, _runs: runs, _stamp: stamp, _initials: initials, _typingLine: typingLine, _blocks: blocks, _isReaction: isReaction };
})();
