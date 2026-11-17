"""우리家 밸런스 — 실행: pip install -r requirements.txt && streamlit run app.py
GitHub에 두 파일을 올린 뒤 Streamlit Community Cloud에서 app.py를 지정하세요.
별도 API 키 불필요. 데이터는 접속 세션에만 보관됩니다. 종료 전 JSON 백업하세요.
공유 데이터베이스/인증이 없는 개인·가족 시연용이며, 의료 진단 도구가 아닙니다.
퀘스트 역할 선택은 인증이 아닙니다. 용돈은 송금되지 않고 지급 여부만 기록합니다.
GitHub Pages는 Python 앱을 실행하지 않습니다. Streamlit Community Cloud에서 배포하세요.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from uuid import uuid4

import pandas as pd
import plotly.express as px
import streamlit as st

COLORS = ['#1751D0', '#E2661E', '#0E9E8F', '#C08A00', '#D95D8F', '#2E7D32', '#9117D0', '#C1232C']
DAYS = ['월', '화', '수', '목', '금', '토', '일']
SLOTS = ['아침', '점심', '저녁']
MENUS = ['홈', '집안일 퀘스트', '함께 식사', '부모님 건강', '가족 설정']


def large_choice(label, options, index=0, format_func=str, key=None, **kwargs):
    """선택지가 화면에 바로 보이는 큰 선택 카드."""
    return st.radio(label, list(options), index=index, format_func=format_func, key=key)


def visible_checks(label, options, default=None, format_func=str, key=None, **kwargs):
    st.write('**' + label + '**')
    chosen = []
    defaults = set(default or [])
    for i, option in enumerate(options):
        if st.checkbox(format_func(option), value=option in defaults,
                       key=f"checks_{key or label}_{i}"):
            chosen.append(option)
    return chosen


def empty_data():
    return {'version': 1, 'members': [], 'chores': [], 'meals': [],
            'availability': [], 'health': [], 'meal_goal': 3, 'quests': []}


def uid():
    return uuid4().hex


def sample_data():
    d = empty_data()
    for name, capacity in [('엄마', 180), ('나', 120), ('오빠', 120)]:
        d['members'].append({'id': uid(), '이름': name, '주간 가능 시간': capacity,
                             '걸음 목표': 6000, '수면 목표': 7.0})
    ids = [m['id'] for m in d['members']]
    for title, minutes, person in [('요리', 210, 0), ('설거지', 105, 0), ('빨래', 60, 0),
                                    ('청소', 90, 1), ('분리수거', 30, 2)]:
        d['chores'].append({'id': uid(), '가사': title, '주간 분': minutes,
                            '담당': ids[person], '가능 담당': ids[:]})
    today = date.today()
    for offset in [1, 3]:
        d['meals'].append({'id': uid(), '날짜': str(today - timedelta(days=offset)),
                           '끼니': '저녁', '참여': ids[:]})
    for member in ids:
        for day in ['수', '토', '일']:
            d['availability'].append({'구성원': member, '요일': day, '끼니': '저녁'})
    for i in range(7):
        d['health'].append({'id': uid(), '구성원': ids[0],
                            '날짜': str(today - timedelta(days=6-i)),
                            '걸음': 4200 + 300*i, '수면': 6.0 + i*0.15,
                            '수축기': None, '이완기': None, '메모': '예시 기록'})
    for title, person, minutes, reward in [('내 방 청소', 1, 20, 2000), ('분리수거', 2, 15, 1500), ('설거지', 1, 20, 2000), ('거실 청소', 2, 30, 3000)]:
        d['quests'].append({'id': uid(), '제목': title, '설명': '끝난 뒤 완료 요청을 눌러 주세요.', '담당': ids[person], '등록자': ids[0], '예상 분': minutes, '용돈': reward, '기한': str(today+timedelta(days=3)), '상태': '진행 중', '완료일': None, '지급일': None})
    return d


def validate_data(raw):
    """백업은 신뢰하지 않고 스키마, 참조, 값 범위를 검증한다."""
    def check(ok, text):
        if not ok:
            raise ValueError(text)
    def number(v, lo, hi):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi
    def text(v, maximum=100):
        return isinstance(v, str) and 0 < len(v.strip()) <= maximum
    check(isinstance(raw, dict) and raw.get('version') == 1, '지원하지 않는 백업 형식입니다.')
    for key in ['members', 'chores', 'meals', 'availability', 'health']:
        check(isinstance(raw.get(key), list) and len(raw[key]) <= 10000, f'{key} 목록이 올바르지 않습니다.')
        check(all(isinstance(r, dict) for r in raw[key]), '목록 형식 오류입니다.')
    check(len(raw['members']) <= 8, '가족은 최대 8명입니다.')
    check(number(raw.get('meal_goal'), 1, 21) and int(raw['meal_goal']) == raw['meal_goal'], '식사 목표 오류입니다.')
    ids = [m.get('id') for m in raw['members']]
    check(all(text(i) for i in ids) and len(set(ids)) == len(ids), '가족 식별자 오류입니다.')
    names = [m.get('이름') for m in raw['members']]
    check(all(text(n, 20) for n in names) and len(set(names)) == len(names), '가족 이름 오류입니다.')
    for m in raw['members']:
        check(number(m.get('주간 가능 시간'), 0, 10080), '가사 가능 시간 오류입니다.')
        check(number(m.get('걸음 목표'), 1, 100000) and number(m.get('수면 목표'), 1, 24), '건강 목표 오류입니다.')
    for key in ['chores', 'meals', 'health']:
        row_ids = [r.get('id') for r in raw[key]]
        check(all(text(i) for i in row_ids) and len(set(row_ids)) == len(row_ids), '기록 식별자 오류입니다.')
    for r in raw['chores']:
        check(text(r.get('가사'), 60) and number(r.get('주간 분'), 1, 10080), '가사 입력 오류입니다.')
        eligible = r.get('가능 담당')
        check(isinstance(eligible, list) and eligible and all(i in ids for i in eligible), '가능 담당 오류입니다.')
        check(r.get('담당') in eligible, '현재 담당자는 가능 담당에 포함되어야 합니다.')
    meal_keys, health_keys, availability_keys = set(), set(), set()
    for r in raw['meals']:
        day = date.fromisoformat(r.get('날짜', ''))
        check(day <= date.today(), '미래 날짜의 식사 완료 기록은 불가합니다.')
        people = r.get('참여')
        check(r.get('끼니') in SLOTS and isinstance(people, list) and len(set(people)) >= 2
              and len(people) == len(set(people)) and all(i in ids for i in people), '식사 참여 정보 오류입니다.')
        key = (r['날짜'], r['끼니'])
        check(key not in meal_keys, '같은 날짜·끼니의 중복 기록입니다.')
        meal_keys.add(key)
    for r in raw['availability']:
        check(r.get('구성원') in ids and r.get('요일') in DAYS and r.get('끼니') in SLOTS, '일정 오류입니다.')
        key = (r['구성원'], r['요일'], r['끼니'])
        check(key not in availability_keys, '중복 일정입니다.')
        availability_keys.add(key)
    for r in raw['health']:
        day = date.fromisoformat(r.get('날짜', ''))
        check(day <= date.today() and r.get('구성원') in ids, '건강 날짜 또는 가족 오류입니다.')
        check(number(r.get('걸음'), 0, 100000) and number(r.get('수면'), 0, 24), '건강 입력 범위 오류입니다.')
        a, b = r.get('수축기'), r.get('이완기')
        check((a is None and b is None) or
              (number(a, 50, 300) and number(b, 30, 200) and a > b), '혈압 값 오류입니다.')
        check(isinstance(r.get('메모'), str) and len(r['메모']) <= 500, '건강 메모 오류입니다.')
        key = (r['구성원'], r['날짜'])
        check(key not in health_keys, '구성원별 하루 건강 기록은 하나여야 합니다.')
        health_keys.add(key)
    if 'quests' not in raw:
        raw['quests'] = []
    check(isinstance(raw['quests'], list) and len(raw['quests']) <= 10000, '퀘스트 목록 오류입니다.')
    quest_ids = set()
    for q in raw['quests']:
        check(isinstance(q, dict), '퀘스트 형식 오류입니다.')
        check(text(q.get('id')) and q['id'] not in quest_ids, '퀘스트 식별자 오류입니다.')
        quest_ids.add(q['id'])
        check(text(q.get('제목'), 60) and isinstance(q.get('설명'), str) and len(q['설명']) <= 500, '퀘스트 설명 오류입니다.')
        check(q.get('담당') in ids and q.get('등록자') in ids, '퀘스트 가족 오류입니다.')
        check(number(q.get('예상 분'), 1, 1440) and number(q.get('용돈'), 0, 1000000) and int(q['용돈']) == q['용돈'], '퀘스트 시간 또는 금액 오류입니다.')
        date.fromisoformat(q.get('기한', ''))
        check(q.get('상태') in ['진행 중', '확인 대기', '지급 대기', '지급 완료'], '퀘스트 상태 오류입니다.')
        for field in ['완료일', '지급일']:
            if q.get(field) is not None:
                check(date.fromisoformat(q[field]) <= date.today(), '완료·지급 날짜 오류입니다.')
        check(q['상태'] not in ['확인 대기', '지급 대기', '지급 완료'] or q.get('완료일') is not None, '완료일이 필요합니다.')
        check(q['상태'] != '지급 완료' or q.get('지급일') is not None, '지급일이 필요합니다.')
    # 알려진 필드만 보관한다.
    return {k: raw[k] for k in empty_data()}


def chore_summary(d):
    total = sum(r['주간 분'] for r in d['chores'])
    capacity = sum(m['주간 가능 시간'] for m in d['members'])
    rows = []
    for m in d['members']:
        actual = sum(r['주간 분'] for r in d['chores'] if r['담당'] == m['id'])
        target = total * m['주간 가능 시간'] / capacity if capacity else 0
        rows.append({'구성원': m['이름'], '현재 분': actual, '기준 분': round(target, 1),
                     '가능 분': m['주간 가능 시간'], '기준 대비 분': round(actual-target, 1)})
    return rows


def propose_chores(d):
    """담당 가능 조건을 지키며, 긴 일부터 상대적 부담을 낮추는 탐욕적 배정."""
    loads = {m['id']: 0 for m in d['members']}
    capacities = {m['id']: m['주간 가능 시간'] for m in d['members']}
    proposals, blocked = [], []
    for r in sorted(d['chores'], key=lambda x: -x['주간 분']):
        eligible = [i for i in r['가능 담당'] if capacities.get(i, 0) > 0]
        if not eligible:
            blocked.append(r['가사'])
            continue
        best = min(eligible, key=lambda i: ((loads[i] + r['주간 분']) / capacities[i], i != r['담당']))
        loads[best] += r['주간 분']
        proposals.append({**r, '담당': best})
    return proposals, blocked


def meal_candidates(d):
    result = []
    for day in DAYS:
        for slot in SLOTS:
            people = list(dict.fromkeys(a['구성원'] for a in d['availability']
                                        if a['요일'] == day and a['끼니'] == slot))
            if len(people) >= 2:
                result.append({'요일': day, '끼니': slot, '가능 인원': len(people), '참여': people})
    return sorted(result, key=lambda x: (-x['가능 인원'], DAYS.index(x['요일']), SLOTS.index(x['끼니'])))


def weekly_meals(d):
    start = date.today() - timedelta(days=date.today().weekday())
    return [r for r in d['meals'] if start <= date.fromisoformat(r['날짜']) <= date.today()]


def chart(frame, x, y, title, line=False):
    if frame.empty:
        st.info('표시할 기록이 없습니다.')
        return
    maker = px.line if line else px.bar
    fig = maker(frame, x=x, y=y, title=title, color_discrete_sequence=COLORS)
    fig.update_layout(paper_bgcolor='#FDFDFF', plot_bgcolor='#FDFDFF',
                      font_color='#1E2433', margin=dict(l=10, r=10, t=55, b=10),
                      legend_title_text='항목', hovermode='x unified')
    fig.update_yaxes(gridcolor='#E2E6F0', rangemode='tozero')
    st.plotly_chart(fig, use_container_width=True)


def names(d):
    return {m['id']: m['이름'] for m in d['members']}


def require_family(d):
    if not d['members']:
        st.info('먼저 ‘가족 설정’에서 가족을 등록해 주세요. 예시 데이터로 둘러볼 수도 있습니다.')
        return False
    return True


def delete_record(d, key, labeler, widget_key):
    if not d[key]:
        return
    with st.expander('기록 삭제'):
        index = large_choice('삭제할 기록', range(len(d[key])),
                             format_func=lambda i: labeler(d[key][i]), key=widget_key)
        confirm = st.checkbox('선택한 기록을 삭제하겠습니다.', key=widget_key+'_confirm')
        if st.button('선택 기록 삭제', key=widget_key+'_button', disabled=not confirm):
            d[key].pop(index)
            st.rerun()


def settings(d):
    st.header('⚙️ 가족 설정')
    st.caption('실명 대신 별칭 사용을 권장합니다. 가능 시간은 가족이 합의하고, 건강 목표는 필요 시 의료진과 정하세요.')
    if d['members']:
        st.dataframe(pd.DataFrame([{k: v for k, v in m.items() if k != 'id'} for m in d['members']]), hide_index=True)
    with st.form('member_add', clear_on_submit=True):
        st.subheader('가족 구성원 추가 · 최대 8명')
        name = st.text_input('이름 또는 별칭', max_chars=20)
        capacity = st.number_input('일주일 가사 가능 시간(분)', 0, 10080, 180, 30)
        steps = st.number_input('개인 하루 걸음 목표(보)', 1, 100000, 6000, 500)
        sleep = st.number_input('개인 하루 수면 목표(시간)', 1.0, 24.0, 7.0, 0.5)
        if st.form_submit_button('가족 추가'):
            if not name.strip() or name.strip() in names(d).values() or len(d['members']) >= 8:
                st.error('중복되지 않는 이름을 입력해 주세요. 최대 8명까지 등록할 수 있습니다.')
            else:
                d['members'].append({'id': uid(), '이름': name.strip(), '주간 가능 시간': capacity,
                                     '걸음 목표': steps, '수면 목표': sleep})
                st.rerun()
    if d['members']:
        with st.expander('구성원 목표 수정'):
            target = large_choice('구성원', list(names(d)), format_func=names(d).get, key='edit_member')
            member = next(m for m in d['members'] if m['id'] == target)
            with st.form('member_edit_'+target):
                cap = st.number_input('가사 가능 시간(분/주)', 0, 10080, int(member['주간 가능 시간']))
                goal = st.number_input('걸음 목표(보/일)', 1, 100000, int(member['걸음 목표']))
                sl = st.number_input('수면 목표(시간/일)', 1.0, 24.0, float(member['수면 목표']))
                if st.form_submit_button('목표 저장'):
                    member.update({'주간 가능 시간': cap, '걸음 목표': goal, '수면 목표': sl})
                    st.rerun()
        st.caption('기록 참조 손상을 방지하기 위해 구성원 개별 삭제는 지원하지 않습니다. 전체 초기화는 아래에서 할 수 있습니다.')
    st.divider()
    st.subheader('데이터 보관')
    st.warning('데이터는 현재 브라우저 접속 세션에만 보관됩니다. 새로고침·재접속·서버 재시작 시 사라질 수 있습니다. 종료 전에 백업하세요. 가족 간 자동 동기화는 지원하지 않습니다.')
    st.download_button('가족 데이터 JSON 백업', json.dumps(d, ensure_ascii=False, indent=2),
                       file_name='우리家밸런스_백업.json', mime='application/json')
    uploaded = st.file_uploader('백업 불러오기 · 최대 2MB', type=['json'])
    consent = st.checkbox('현재 데이터를 백업 파일로 교체하는 데 동의합니다.')
    if st.button('백업 복원', disabled=uploaded is None or not consent):
        try:
            if uploaded.size > 2 * 1024 * 1024:
                raise ValueError('백업은 2MB 이하여야 합니다.')
            restored = validate_data(json.loads(uploaded.getvalue().decode('utf-8-sig')))
            st.session_state.data = restored
            st.session_state.example = False
            st.rerun()
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            st.error(f'복원하지 못했습니다. 유효한 앱 백업인지 확인하세요. {exc}')
    with st.expander('예시 데이터 / 전체 초기화'):
        st.caption('예시는 실제 가족 기록이 아닙니다. 현재 데이터가 교체됩니다.')
        agreed = st.checkbox('현재 데이터를 교체하는 데 동의합니다.', key='reset_consent')
        left, right = st.columns(2)
        if left.button('예시 데이터로 교체', disabled=not agreed):
            st.session_state.data = sample_data()
            st.session_state.example = True
            st.rerun()
        if right.button('전체 기록 초기화', disabled=not agreed):
            st.session_state.data = empty_data()
            st.session_state.example = False
            st.rerun()


def transition_quest(q, action, actor):
    rules = {'완료 요청': ('진행 중', '확인 대기', q['담당']),
             '완료 승인': ('확인 대기', '지급 대기', q['등록자']),
             '다시 요청': ('확인 대기', '진행 중', q['등록자']),
             '지급 완료': ('지급 대기', '지급 완료', q['등록자'])}
    if action not in rules:
        raise ValueError('허용되지 않은 작업입니다.')
    before, after, allowed = rules[action]
    if actor != allowed or q['상태'] != before:
        raise ValueError('담당자 또는 현재 상태가 맞지 않습니다.')
    q['상태'] = after
    if action == '완료 요청':
        q['완료일'] = str(date.today())
    if action == '다시 요청':
        q['완료일'] = None
    if action == '지급 완료':
        q['지급일'] = str(date.today())


def quest_summary(d):
    rows = []
    for m in d['members']:
        assigned = [q for q in d['quests'] if q['담당'] == m['id']]
        rows.append({'구성원': m['이름'],
                     '배정 시간(분)': sum(q['예상 분'] for q in assigned),
                     '승인된 완료 시간(분)': sum(q['예상 분'] for q in assigned if q['상태'] in ['지급 대기', '지급 완료']),
                     '지급 대기(원)': sum(q['용돈'] for q in assigned if q['상태'] == '지급 대기'),
                     '지급 완료(원)': sum(q['용돈'] for q in assigned if q['상태'] == '지급 완료')})
    return rows


def home(d):
    st.header('🏡 우리 가족, 오늘도 균형 있게')
    st.write('집안일은 퀘스트로, 식사는 함께, 건강은 꾸준하게!')
    st.metric('진행 중인 집안일', f"{sum(q['상태']=='진행 중' for q in d['quests'])}개")
    st.metric('확인이 필요한 퀘스트', f"{sum(q['상태']=='확인 대기' for q in d['quests'])}개")
    st.metric('승인 후 지급할 용돈', f"{sum(q['용돈'] for q in d['quests'] if q['상태']=='지급 대기'):,}원")
    st.metric('이번 주 함께한 식사', f"{len(weekly_meals(d))} / {d['meal_goal']}회")
    if not require_family(d):
        return
    st.subheader('오늘의 실천 제안')
    overdue = [q for q in d['quests'] if q['상태']=='진행 중' and q['기한'] < str(date.today())]
    if overdue:
        st.warning(f'기한이 지난 퀘스트 {len(overdue)}개가 있어요. 혼내기보다 양과 시간을 함께 조정해 보세요.')
    else:
        st.info('집안일 퀘스트에서 할 일을 확인하고, 끝나면 완료 요청을 눌러 주세요.')
    candidates = meal_candidates(d)
    if candidates:
        best = candidates[0]
        st.success(f"매주 {best['요일']}요일 {best['끼니']}에 {best['가능 인원']}명이 식사할 수 있어요. 메뉴와 준비 담당을 함께 정해 보세요.")
    else:
        st.info('함께 식사 메뉴에서 가능한 요일과 끼니를 등록해 보세요.')
    st.info('부모님 건강 메뉴에서 기록과 병원 상담 안내를 확인하세요. 응급 증상은 기록보다 119 도움을 우선하세요.')


def quests(d):
    st.header('🎯 집안일 퀘스트')
    if not require_family(d):
        return
    n = names(d)
    st.info('완료 요청 → 등록한 보호자 승인 → 실제 용돈 지급 → 지급 완료 기록. 앱이 돈을 송금하지는 않습니다.')
    st.warning('현재 사용자 선택은 가족끼리 쓰는 시연용입니다. 로그인·비밀번호 인증이 아니므로 다른 사람의 역할 선택을 기술적으로 막지는 않습니다.')
    actor = large_choice('지금 사용하는 가족', list(n), format_func=n.get, key='quest_actor')
    tab1, tab2, tab3 = st.tabs(['퀘스트 목록', '퀘스트 만들기', '분담·용돈 분석'])
    with tab2:
        st.write('엄마 등 보호자가 자기 이름으로 퀘스트를 등록하세요. 여러 명을 선택하면 각자에게 별도의 퀘스트가 생깁니다.')
        with st.form('new_quest', clear_on_submit=True):
            title = st.text_input('할 일', max_chars=60, placeholder='예: 방 청소, 설거지, 분리수거')
            detail = st.text_area('어떻게 하면 완료인가요?', max_chars=500, placeholder='예: 책상 정리하고 바닥까지 청소하기')
            people = visible_checks('누가 할까요?', list(n), format_func=n.get)
            minutes = st.number_input('한 사람당 예상 시간(분)', 1, 1440, 20)
            reward = st.number_input('한 사람당 용돈(원)', 0, 1000000, 2000, 100)
            deadline = st.date_input('완료 기한', min_value=date.today())
            consent = st.checkbox('보호자로서 안전과 용돈을 가족과 합의했습니다.')
            if st.form_submit_button('퀘스트 등록', use_container_width=True):
                if not title.strip() or not people or not consent:
                    st.error('할 일, 담당자, 합의 확인을 모두 입력해 주세요.')
                else:
                    for person in people:
                        d['quests'].append({'id': uid(), '제목': title.strip(), '설명': detail,
                                            '담당': person, '등록자': actor, '예상 분': minutes,
                                            '용돈': reward, '기한': str(deadline), '상태': '진행 중',
                                            '완료일': None, '지급일': None})
                    st.rerun()
    with tab1:
        scope = large_choice('보고 싶은 퀘스트', ['나와 관련된 퀘스트', '가족 전체 퀘스트'])
        status = large_choice('진행 상태', ['전체', '진행 중', '확인 대기', '지급 대기', '지급 완료'])
        visible = [q for q in d['quests'] if (scope=='가족 전체 퀘스트' or actor in [q['담당'], q['등록자']]) and (status=='전체' or q['상태']==status)]
        if not visible:
            st.info('해당 퀘스트가 없습니다. 퀘스트 만들기에서 할 일을 등록하세요.')
        for q in sorted(visible, key=lambda x: x['기한']):
            with st.container(border=True):
                st.subheader(q['제목'])
                st.write(f"담당: {n[q['담당']]} · 등록: {n[q['등록자']]}")
                st.write(f"💰 {q['용돈']:,}원 · ⏱ {q['예상 분']}분")
                st.write(f"기한: {q['기한']} · 상태: **{q['상태']}**")
                if q['설명']:
                    st.write(q['설명'])
                actions = []
                if q['상태']=='진행 중' and actor==q['담당']:
                    actions = ['완료 요청']
                if actor==q['등록자'] and q['상태']=='확인 대기':
                    actions = ['완료 승인', '다시 요청']
                if actor==q['등록자'] and q['상태']=='지급 대기':
                    paid = st.checkbox('실제로 용돈을 지급했습니다.', key='paid_'+q['id'])
                    if paid:
                        actions = ['지급 완료']
                for action in actions:
                    if st.button(action, key=action+q['id'], use_container_width=True):
                        transition_quest(q, action, actor)
                        st.rerun()
    with tab3:
        st.write('현재 등록된 전체 퀘스트 기준입니다. 예상 시간은 실제 완료 시간이 아닙니다.')
        if not d['quests']:
            st.info('퀘스트를 등록하면 가족별 분담과 용돈을 분석합니다.')
        else:
            frame = pd.DataFrame(quest_summary(d))
            chart(frame, '구성원', ['배정 시간(분)', '승인된 완료 시간(분)'], '가족별 퀘스트 분담 시간(분)')
            st.dataframe(frame, hide_index=True)
            total = sum(q['예상 분'] for q in d['quests'])
            cap = sum(m['주간 가능 시간'] for m in d['members'])
            if cap:
                comparisons = [(m, frame.iloc[i]['배정 시간(분)']-total*m['주간 가능 시간']/cap) for i,m in enumerate(d['members'])]
                heavy, extra = max(comparisons, key=lambda x:x[1])
                if extra > 0:
                    st.info(f"가능 시간 비례 기준보다 {heavy['이름']}에게 약 {extra:.0f}분 더 배정되어 있어요. 새 퀘스트는 여유 있는 가족에게 맡기거나 일을 작게 나눠 보세요.")
                st.write('가족 설정의 주간 가능 시간 비율을 참고합니다. 퀘스트 전체 기간과 주간 가능 시간은 기간이 다를 수 있으므로 분담 비율만 비교하며 공정성의 절대 기준은 아닙니다.')
            st.write('해결 방법: 비슷한 난이도에는 비슷한 보상을 정하고, 위험하거나 무거운 일은 아이에게 맡기지 마세요. 용돈 없는 공동 책임도 가족끼리 합의하세요.')


def meals(d):
    st.header('🍚 함께 식사')
    if not require_family(d):
        return
    n = names(d)
    goal = st.number_input('이번 주 함께 식사 목표(회)', 1, 21, int(d['meal_goal']))
    d['meal_goal'] = goal
    st.caption('가족 2명 이상이 함께한 끼니를 1회로 계산합니다. 같은 날짜·끼니는 중복 계산하지 않습니다.')
    tab1, tab2 = st.tabs(['가능 시간 찾기', '식사 기록·분석'])
    with tab1:
        who = large_choice('가능 시간을 등록할 가족', list(n), format_func=n.get)
        existing = [f"{r['요일']}요일 {r['끼니']}" for r in d['availability'] if r['구성원'] == who]
        with st.form('availability_'+who):
            slots = visible_checks('매주 함께 식사 가능한 시간', [f'{day}요일 {slot}' for day in DAYS for slot in SLOTS], default=existing)
            if st.form_submit_button('가능 시간 저장'):
                d['availability'] = [r for r in d['availability'] if r['구성원'] != who]
                for value in slots:
                    day, slot = value.split('요일 ')
                    d['availability'].append({'구성원': who, '요일': day, '끼니': slot})
                st.rerun()
        result = meal_candidates(d)
        if result:
            st.subheader('많이 모일 수 있는 정기 식사 후보')
            st.dataframe(pd.DataFrame([{'요일': r['요일'], '끼니': r['끼니'], '가능 인원': r['가능 인원'],
                                        '가족': ', '.join(n[i] for i in r['참여'])} for r in result]), hide_index=True)
            st.write('실천 방법: 상위 후보를 가족 일정에 고정하고, 장보기와 조리 담당을 나누세요. 가능한 사람이 적다면 요일이나 끼니를 바꿔 다시 합의하세요.')
        else:
            st.info('겹치는 시간이 아직 없습니다. 두 명 이상의 일정을 등록하거나 20분의 짧은 식사부터 합의해 보세요.')
    with tab2:
        with st.form('meal_add', clear_on_submit=True):
            day = st.date_input('식사한 날짜', max_value=date.today())
            slot = large_choice('함께한 끼니', SLOTS)
            people = visible_checks('참여한 가족', list(n), format_func=n.get)
            if st.form_submit_button('식사 기록 저장'):
                if len(people) < 2:
                    st.error('가족 2명 이상을 선택해 주세요.')
                elif any(r['날짜'] == str(day) and r['끼니'] == slot for r in d['meals']):
                    st.error('이미 기록된 끼니입니다. 아래 기록을 삭제하고 다시 입력하세요.')
                else:
                    d['meals'].append({'id': uid(), '날짜': str(day), '끼니': slot, '참여': people})
                    st.rerun()
        records = weekly_meals(d)
        st.metric('이번 주 함께한 식사', f'{len(records)}회', f'목표까지 {max(0, goal-len(records))}회 남음', delta_color='off')
        st.progress(min(1.0, len(records)/goal))
        start = date.today() - timedelta(days=date.today().weekday())
        frame = pd.DataFrame([{'요일': DAYS[i], '함께한 식사(회)': sum(r['날짜'] == str(start+timedelta(days=i)) for r in records)}
                              for i in range(date.today().weekday()+1)])
        chart(frame, '요일', '함께한 식사(회)', '이번 주 요일별 함께한 식사')
        st.dataframe(frame, hide_index=True)
        for member in d['members']:
            count = sum(member['id'] in r['참여'] for r in records)
            st.write(f"• {member['이름']}: 이번 주 {count}회 참여")
        if d['meals']:
            st.dataframe(pd.DataFrame([{'날짜': r['날짜'], '끼니': r['끼니'], '가족': ', '.join(n[i] for i in r['참여'])}
                                        for r in sorted(d['meals'], key=lambda r: r['날짜'], reverse=True)]), hide_index=True)
        delete_record(d, 'meals', lambda r: f"{r['날짜']} {r['끼니']}", 'del_meal')


def care_advice(symptoms):
    emergency = {'흉통 또는 심한 호흡곤란', '갑작스러운 마비 또는 언어 장애', '의식 저하 또는 실신'}
    if emergency.intersection(symptoms):
        return ('응급 증상일 수 있습니다. 기록을 계속하기보다 즉시 119 또는 응급실 도움을 받으세요. 혼자 운전하지 마세요.', None)
    if symptoms:
        return (None, '반복되거나 생활에 지장을 주는 증상이 있어 병원 방문·의료진 상담을 권장합니다. 증상 발생 시점과 건강 기록을 준비하세요. 갑자기 심해지면 즉시 도움을 받으세요.')
    return (None, None)


def health(d):
    st.header('💚 부모님 건강')
    st.warning('생활 습관 참고용이며 진단·치료·복약 지시를 제공하지 않습니다. 개인 목표는 연령·건강 상태에 맞춰 의료진과 정하세요. 흉통, 호흡곤란, 갑작스러운 마비·언어 장애 등 급성 증상은 수치와 관계없이 119 또는 응급실 도움을 받으세요.')
    st.subheader('지금 병원 도움이 필요한가요?')
    symptoms = visible_checks('현재 해당되는 상황을 선택하세요',
        ['흉통 또는 심한 호흡곤란', '갑작스러운 마비 또는 언어 장애', '의식 저하 또는 실신',
         '반복되는 어지럼·두통 또는 일상생활 불편', '혈압이 반복해서 평소와 크게 다름',
         '수면·피로 문제가 계속됨'], key='symptom_check')
    urgent, consultation = care_advice(symptoms)
    if urgent:
        st.error(urgent)
    elif consultation:
        st.warning(consultation)
    else:
        st.info('증상을 선택하면 상담 안내를 드립니다. 선택하지 않았다고 건강에 이상이 없다는 뜻은 아닙니다.')
    st.write('아래 안내는 자가 입력에 따른 일반적인 도움말입니다. 기록만으로 질병을 판단하거나 약을 바꾸지 마세요.')
    if not require_family(d):
        return
    n = names(d)
    who = large_choice('건강을 살펴볼 가족', list(n), format_func=n.get)
    member = next(m for m in d['members'] if m['id'] == who)
    st.caption('당사자의 동의를 받고 기록하세요. 0은 실제 0으로 분석되므로 측정한 항목만 확인해 입력하세요. 혈압은 선택 사항입니다.')
    with st.form('health_add_'+who, clear_on_submit=True):
        day = st.date_input('기록 날짜', max_value=date.today())
        steps = st.number_input('하루 걸음 수(보)', 0, 100000, 0, 100)
        sleep = st.number_input('수면 시간(시간)', 0.0, 24.0, 7.0, 0.5)
        bp = st.checkbox('혈압도 함께 기록')
        st.caption('혈압 체크 후 수치를 입력하고 저장하세요. 혈압은 의학적 정상 여부를 자동 판정하지 않습니다.')
        systolic = st.number_input('수축기 혈압(mmHg)', 50, 300, 120)
        diastolic = st.number_input('이완기 혈압(mmHg)', 30, 200, 80)
        memo = st.text_area('몸 상태·진료 때 물어볼 점', max_chars=500)
        confirmed = st.checkbox('걸음과 수면은 실제 확인한 값입니다.')
        if st.form_submit_button('건강 기록 저장 · 같은 날짜는 수정'):
            if not confirmed:
                st.error('걸음과 수면 값을 확인해 주세요.')
            elif bp and systolic <= diastolic:
                st.error('수축기 혈압은 이완기 혈압보다 커야 합니다.')
            else:
                d['health'] = [r for r in d['health'] if not (r['구성원'] == who and r['날짜'] == str(day))]
                d['health'].append({'id': uid(), '구성원': who, '날짜': str(day), '걸음': steps,
                                    '수면': sleep, '수축기': systolic if bp else None,
                                    '이완기': diastolic if bp else None, '메모': memo})
                st.rerun()
    period = large_choice('분석 기간', [7, 14, 30], format_func=lambda x: f'최근 {x}일')
    start = date.today() - timedelta(days=period-1)
    records = sorted([r for r in d['health'] if r['구성원'] == who and start <= date.fromisoformat(r['날짜']) <= date.today()], key=lambda r: r['날짜'])
    if not records:
        st.info('선택한 기간의 기록이 없습니다.')
    else:
        frame = pd.DataFrame(records)
        mean_steps, mean_sleep = frame['걸음'].mean(), frame['수면'].mean()
        a, b, c = st.columns(3)
        a.metric('기록일 평균 걸음', f'{mean_steps:,.0f}보')
        b.metric('기록일 평균 수면', f'{mean_sleep:.1f}시간')
        c.metric('기록 일수', f'{len(records)} / {period}일')
        st.caption('누락 날짜는 0으로 계산하지 않습니다. 그래프는 달력 날짜를 채워 누락 구간을 끊어 표시합니다. 기록일 평균만으로 전체 기간을 판단하지 마세요.')
        steps_rate = 100 * sum(r['걸음'] >= member['걸음 목표'] for r in records) / len(records)
        sleep_rate = 100 * sum(r['수면'] >= member['수면 목표'] for r in records) / len(records)
        st.write(f"개인 목표 충족일 비율: 걸음 {steps_rate:.0f}% · 수면 {sleep_rate:.0f}% (분모: 기록일 {len(records)}일)")
        st.caption('수면 목표 충족은 설정 시간 이상이라는 뜻이며, 길수록 건강하다는 의미는 아닙니다.')
        if mean_steps < member['걸음 목표']:
            st.info(f"걷기 실천: 기록일 평균이 개인 목표보다 {member['걸음 목표']-mean_steps:,.0f}보 적습니다. 무리하지 않는 범위에서 짧은 산책을 가족과 나눠 시도하세요.")
        else:
            st.success('걷기: 설정한 개인 목표를 평균적으로 충족했습니다. 통증이나 피로가 있으면 운동량을 조절하고 상담하세요.')
        if mean_sleep < member['수면 목표']:
            st.info('수면 실천: 설정한 수면 목표보다 평균이 짧습니다. 일정한 취침 시간과 편안한 수면 환경을 함께 준비하세요.')
        else:
            st.write('수면: 설정한 시간 목표 이상입니다. 과도한 졸림이나 수면 불편이 있으면 별도로 상담하세요.')
        calendar = pd.DataFrame({'날짜': pd.date_range(start, date.today()).strftime('%Y-%m-%d')})
        plotted = calendar.merge(frame, on='날짜', how='left')
        plotted['걸음 목표'] = member['걸음 목표']
        plotted['수면 목표'] = member['수면 목표']
        chart(plotted, '날짜', ['걸음', '걸음 목표'], '걸음 수와 개인 목표(보)', True)
        chart(plotted, '날짜', ['수면', '수면 목표'], '수면 시간과 개인 목표(시간)', True)
        blood = frame[frame['수축기'].notna()]
        if not blood.empty:
            chart(plotted, '날짜', ['수축기', '이완기'], '기록한 혈압 추이(mmHg) · 의료진 상담 참고', True)
            st.caption('혈압 수치가 걱정되거나 반복해서 평소와 다르면 측정 방법을 확인하고 의료진과 상담하세요. 앱을 근거로 약을 변경하지 마세요.')
        show = frame.drop(columns=['id', '구성원']).rename(columns={'걸음': '걸음(보)', '수면': '수면(시간)', '수축기': '수축기(mmHg)', '이완기': '이완기(mmHg)'})
        st.dataframe(show, hide_index=True)
        st.download_button('선택 기간 건강 기록 CSV', show.to_csv(index=False).encode('utf-8-sig'),
                           file_name='건강기록.csv', mime='text/csv')
    delete_record(d, 'health', lambda r: f"{n[r['구성원']]} · {r['날짜']}", 'del_health')


def main():
    st.set_page_config(page_title='우리家 밸런스', page_icon='🏡', layout='centered')
    st.markdown('''<style>
    .stApp {font-family: 'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
    .block-container {max-width:850px;padding-top:1.2rem;padding-bottom:3rem;}
    .stApp p, .stApp label, .stApp li, .stApp input, .stApp textarea, .stApp [data-testid="stCaptionContainer"] p {font-size:22px !important;line-height:1.65;}
    .stApp button, .stApp [data-baseweb="select"] {min-height:64px;}
    .stApp button p {font-size:22px !important;}
    [role="tab"] {min-height:64px;padding:12px;}
    [data-testid="stVerticalBlockBorderWrapper"] {border-radius:18px;}
    div[data-testid="stMetric"] {background:#FDFDFF;border:1px solid #E2E6F0;border-radius:16px;padding:18px;color:#1E2433;}
    .brand {padding:42px 28px;border-radius:24px;background:#E8EEFB;color:#1E2433;text-align:center;margin:20px 0;}
    .brand h1 {font-size:clamp(2rem,6vw,3.6rem);color:#1E2433;}
    .brand p {font-size:1.15rem;}
    button {min-height:64px;}
    [data-testid="stRadio"] [role="radiogroup"] {gap:10px;}
    [data-testid="stRadio"] [role="radiogroup"] > label {
        width:100%; min-height:64px; padding:14px 16px;
        border:2px solid #CDD5E4; border-radius:16px; box-sizing:border-box;
        cursor:pointer; align-items:center;
    }
    [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) {
        border-color:#1751D0;background:#E8EEFB;
    }
    [data-testid="stCheckbox"] > label {min-height:64px; padding:10px 8px; align-items:center;}
    [data-testid="stCheckbox"] input {min-width:28px; min-height:28px;}
    .stApp input, .stApp textarea {font-size:22px !important; min-height:56px;}
    .stApp h1 {font-size:36px !important;}
    .stApp h2 {font-size:30px !important;}
    .stApp h3 {font-size:26px !important;}
    [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"],
    [data-testid="stFormSubmitButton"] button {width:100%;white-space:normal;}
    [role="tablist"] {flex-wrap:wrap;gap:8px;height:auto !important;}
    [role="tab"] {border:2px solid #CDD5E4;border-radius:14px;flex:1 1 100%;white-space:normal;}
    [role="tab"][aria-selected="true"] {background:#E8EEFB;border-color:#1751D0;}
    @media(max-width:640px) {
        .block-container {padding-left:16px;padding-right:16px;}
        [data-testid="stHorizontalBlock"] {flex-direction:column;}
        [data-testid="stColumn"] {width:100% !important;flex:1 1 100% !important;min-width:100% !important;}
    }
    </style>''', unsafe_allow_html=True)
    if 'data' not in st.session_state:
        st.session_state.data = empty_data()
        st.session_state.example = False
    if not st.session_state.get('started', False):
        st.markdown('<div class="brand"><div style="font-size:80px" aria-hidden="true">🏡</div><h1>우리家 밸런스</h1><p>함께 나누면, 우리 가족이 더 행복해져요.</p></div>', unsafe_allow_html=True)
        st.write('집안일 퀘스트로 부담을 나누고, 함께 밥 먹고, 부모님 건강도 챙겨요.')
        if st.button('시작하기 →', use_container_width=True, type='primary'):
            st.session_state.started = True
            st.session_state.main_menu = '홈'
            st.rerun()
        return
    st.title('🏡 우리家 밸런스')
    page = large_choice('하고 싶은 일을 눌러 주세요', MENUS, key='main_menu')
    st.write('접속 세션에만 저장됩니다. 가족 설정에서 백업해 주세요.')
    if st.button('로고·시작 화면으로', use_container_width=True):
        st.session_state.started = False
        st.rerun()
    d = st.session_state.data
    if st.session_state.get('example', False):
        st.warning('예시 가족 데이터입니다. 실제 사용 전 ‘가족 설정’에서 전체 초기화해 주세요.')
    {'홈': home, '집안일 퀘스트': quests, '함께 식사': meals,
     '부모님 건강': health, '가족 설정': settings}[page](d)
    st.divider()
    st.caption('우리家 밸런스 | 분석은 입력 데이터와 공개된 계산 규칙을 사용합니다. 외부 AI 전송 없음. 실시간 가족 공유·로그인은 포함되지 않습니다.')


if __name__ == '__main__':
    main()
