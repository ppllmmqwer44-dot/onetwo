"""우리家 밸런스 — 실행: pip install -r requirements.txt && streamlit run app.py
GitHub에 두 파일을 올린 뒤 Streamlit Community Cloud에서 app.py를 지정하세요.
별도 API 키 불필요. 데이터는 접속 세션에만 보관됩니다. 종료 전 JSON 백업하세요.
공유 데이터베이스/인증이 없는 개인·가족 시연용이며, 의료 진단 도구가 아닙니다.
퀘스트 역할 선택은 인증이 아닙니다. 용돈은 송금되지 않고 지급 여부만 기록합니다.
GitHub Pages는 Python 앱을 실행하지 않습니다. Streamlit Community Cloud에서 배포하세요.
"""
from __future__ import annotations

import base64
import io
from PIL import Image, ImageOps
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


def go_page(page):
    st.session_state.main_menu = page


def large_choice(label, options, index=0, format_func=str, key=None, **kwargs):
    options = list(options)
    value = st.pills(label, options, selection_mode='single', default=options[index],
                     format_func=format_func, key=key)
    return options[index] if value is None else value


def visible_checks(label, options, default=None, format_func=str, key=None, **kwargs):
    return st.pills(label, list(options), selection_mode='multi', default=default or [],
                    format_func=format_func, key=key) or []


def empty_data():
    return {'version': 1, 'members': [], 'chores': [], 'meals': [],
            'availability': [], 'health': [], 'meal_goal': 3, 'quests': []}


def uid():
    return uuid4().hex


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
        check(number(q.get('용돈'), 0, 1000000) and int(q['용돈']) == q['용돈'], '미션금 오류입니다.')
        q.pop('예상 분', None)
        q.pop('기한', None)
        photo = q.get('사진')
        if photo is not None:
            check(isinstance(photo, str) and len(photo) <= 1500000, '사진 크기 오류입니다.')
            try:
                image_bytes = base64.b64decode(photo, validate=True)
                with Image.open(io.BytesIO(image_bytes)) as image:
                    check(image.format == 'JPEG' and max(image.size) <= 1280, '사진 형식 오류입니다.')
                    image.verify()
            except Exception as exc:
                raise ValueError('백업 사진을 확인할 수 없습니다.') from exc
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
        st.write('표시할 기록이 없습니다.')
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
        st.write('아직 등록한 가족이 없어요. 아래 버튼으로 가족 이름부터 등록해 주세요.')
        st.button('👨‍👩‍👧‍👦 가족 등록하러 가기', on_click=go_page, args=('가족 설정',), key='register_family_now', use_container_width=True, type='primary')
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


def add_family_member(d, name):
    name = name.strip()
    if not name or len(name) > 20:
        raise ValueError('가족 호칭을 1~20자로 입력해 주세요.')
    if name in names(d).values():
        raise ValueError('이미 등록된 가족이에요.')
    if len(d['members']) >= 8:
        raise ValueError('가족은 최대 8명까지 등록할 수 있어요.')
    d['members'].append({'id': uid(), '이름': name, '주간 가능 시간': 180,
                         '걸음 목표': 6000, '수면 목표': 7.0})


def settings(d):
    st.header('👨‍👩‍👧‍👦 우리 가족 등록')
    st.write('가족 구성원을 한 명씩 입력하고 추가해 주세요. 이름 대신 엄마·첫째 오빠 같은 호칭도 좋아요.')
    if d['members']:
        st.subheader('등록된 우리 가족')
        for member in d['members']:
            st.success('👤 '+member['이름'])
    else:
        st.write('아래에 첫 번째 가족의 이름이나 호칭을 입력해 주세요.')
    st.subheader('가족 한 명 추가하기')
    with st.form('custom_family', clear_on_submit=True):
        name = st.text_input('이름 또는 가족 호칭', max_chars=20, placeholder='예: 나, 엄마, 아빠, 첫째 오빠')
        if st.form_submit_button('입력한 가족 추가하기', use_container_width=True):
            try:
                add_family_member(d, name)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if d['members']:
        st.button('🎯 미션 등록하러 가기', on_click=go_page, args=('집안일 퀘스트',),
                  key='family_to_quests', use_container_width=True, type='primary')
        with st.expander('선택 사항 · 건강 목표와 호칭 수정'):
            st.write('초기 건강 목표는 개인 처방이 아닙니다. 본인의 건강 상태와 의료진 권고에 맞게 바꿔 주세요.')
            target = large_choice('수정할 가족', list(names(d)), format_func=names(d).get, key='edit_member')
            member = next(m for m in d['members'] if m['id']==target)
            with st.form('member_edit_'+target):
                new_name = st.text_input('가족 호칭', value=member['이름'], max_chars=20)
                goal = st.number_input('하루 걸음 목표(보)', 1, 100000, int(member['걸음 목표']), 500)
                sl = st.number_input('하루 수면 목표(시간)', 1.0, 24.0, float(member['수면 목표']), 0.5)
                if st.form_submit_button('수정 내용 저장', use_container_width=True):
                    clean = new_name.strip()
                    if not clean or any(m['id']!=target and m['이름']==clean for m in d['members']):
                        st.error('중복되지 않는 가족 호칭을 입력해 주세요.')
                    else:
                        member.update({'이름': clean, '걸음 목표': goal, '수면 목표': sl})
                        st.rerun()
    with st.expander('전체 기록 초기화'):
        agreed = st.checkbox('사진과 미션금을 포함한 모든 기록 삭제에 동의합니다.', key='reset_consent')
        if st.button('전체 기록 초기화', disabled=not agreed, use_container_width=True):
            st.session_state.data = empty_data()
            st.rerun()


def prepare_photo(raw):
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError('사진은 10MB 이하로 올려 주세요.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ['JPEG', 'PNG', 'WEBP'] or source.width * source.height > 25000000:
                raise ValueError('JPG, PNG, WEBP 사진을 사용해 주세요. 최대 2,500만 화소입니다.')
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1280, 1280))
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=78, optimize=True)
            return base64.b64encode(output.getvalue()).decode('ascii')
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError('사진을 열 수 없습니다. 다른 JPG·PNG 사진을 선택해 주세요.') from exc


def transition_quest(q, action, actor):
    if action == '사진으로 미션 완료':
        if actor != q['담당'] or q['상태'] != '진행 중' or not q.get('사진'):
            raise ValueError('담당자가 완료 사진을 먼저 올려 주세요.')
        q['상태'] = '지급 대기'
        q['완료일'] = str(date.today())
    elif action == '지급 완료':
        if actor != q['등록자'] or q['상태'] != '지급 대기':
            raise ValueError('미션을 등록한 가족만 지급 완료를 기록할 수 있습니다.')
        q['상태'] = '지급 완료'
        q['지급일'] = str(date.today())
    else:
        raise ValueError('허용되지 않은 작업입니다.')


def quest_summary(d):
    return [{'구성원': m['이름'],
             '배정 미션(개)': sum(q['담당']==m['id'] for q in d['quests']),
             '완료 미션(개)': sum(q['담당']==m['id'] and q['상태'] in ['지급 대기','지급 완료'] for q in d['quests']),
             '받을 미션금(원)': sum(q['용돈'] for q in d['quests'] if q['담당']==m['id'] and q['상태']=='지급 대기'),
             '받은 미션금(원)': sum(q['용돈'] for q in d['quests'] if q['담당']==m['id'] and q['상태']=='지급 완료')}
            for m in d['members']]


def home(d):
    st.header('🏡 우리 가족, 오늘도 균형 있게')
    st.write('집안일은 퀘스트로, 식사는 함께, 건강은 꾸준하게!')
    st.metric('진행 중인 집안일', f"{sum(q['상태']=='진행 중' for q in d['quests'])}개")
    st.metric('완료한 미션', f"{sum(q['상태'] in ['지급 대기', '지급 완료'] for q in d['quests'])}개")
    st.metric('승인 후 지급할 용돈', f"{sum(q['용돈'] for q in d['quests'] if q['상태']=='지급 대기'):,}원")
    st.metric('이번 주 함께한 식사', f"{len(weekly_meals(d))} / {d['meal_goal']}회")
    if not require_family(d):
        return
    st.subheader('오늘의 실천 제안')
    st.write('집안일 퀘스트에서 미션을 고르고, 완료 사진을 올려 미션금을 모아 보세요. 시간 제한은 없어요.')
    candidates = meal_candidates(d)
    if candidates:
        best = candidates[0]
        st.success(f"매주 {best['요일']}요일 {best['끼니']}에 {best['가능 인원']}명이 식사할 수 있어요. 메뉴와 준비 담당을 함께 정해 보세요.")
    else:
        st.write('함께 식사 메뉴에서 가능한 요일과 끼니를 등록해 보세요.')
    st.write('부모님 건강 메뉴에서 기록과 병원 상담 안내를 확인하세요. 응급 증상은 기록보다 119 도움을 우선하세요.')


def group_missions(quests):
    groups = {}
    for q in quests:
        # 이전 버전 기록은 제목·설명·등록자·금액이 같으면 함께 표시합니다.
        key = ('group', q['그룹']) if q.get('그룹') else ('legacy', q['제목'], q.get('설명', ''), q['등록자'], q['용돈'])
        groups.setdefault(key, []).append(q)
    return list(groups.values())


def quests(d):
    st.header('🎯 집안일 퀘스트')
    if not require_family(d):
        return
    n = names(d)
    st.write('할 일을 끝내고 사진을 올리면 미션 완료! 정해진 시간이나 마감일은 없어요.')
    actor = large_choice('누가 사용하나요?', list(n), format_func=n.get, key='quest_actor')
    tab1, tab2, tab3 = st.tabs(['내 미션', '미션 등록', '미션금·가족 분담'])
    with tab2:
        st.subheader('가족 누구나 미션을 등록할 수 있어요')
        st.write('현재 선택한 가족 이름으로 등록됩니다. 여러 담당자를 골라도 미션 카드는 하나로 보여요. 사진 제출과 미션금은 각자 따로 기록해요.')
        with st.form('new_quest', clear_on_submit=True):
            title = st.text_input('어떤 집안일인가요?', max_chars=60, placeholder='예: 설거지하기')
            detail = st.text_input('완료 기준 (선택)', max_chars=500, placeholder='예: 싱크대 정리까지')
            people = visible_checks('누가 할까요?', list(n), format_func=n.get)
            reward = st.number_input('한 사람에게 줄 미션금(원)', 0, 1000000, 2000, 100)
            consent = st.checkbox('안전과 미션금을 가족과 합의했습니다.')
            if st.form_submit_button('미션 등록하기', use_container_width=True):
                if not title.strip() or not people or not consent:
                    st.error('할 일과 담당자를 입력하고 합의를 확인해 주세요.')
                else:
                    group_id = uid()
                    for person in people:
                        d['quests'].append({'id': uid(), '그룹': group_id, '제목': title.strip(), '설명': detail,
                                            '담당': person, '등록자': actor, '용돈': reward,
                                            '상태': '진행 중', '사진': None, '완료일': None, '지급일': None})
                    st.rerun()
    with tab1:
        groups = group_missions(d['quests'])
        visible = [group for group in groups if any(actor in [q['담당'], q['등록자']] for q in group)]
        if not visible:
            st.write('아직 미션이 없어요. 미션 등록에서 가족의 첫 미션을 만들어 주세요.')
        for group in reversed(visible):
            first = group[0]
            with st.container(border=True):
                st.subheader('🎯 '+first['제목'])
                st.write('등록한 가족: '+n[first['등록자']])
                st.divider()
                st.write('**함께할 가족**')
                st.write(' · '.join(n[q['담당']] for q in group))
                if len({q['용돈'] for q in group}) == 1:
                    st.write(f"💰 1인당 미션금 {first['용돈']:,}원")
                else:
                    st.write('미션금: '+ ' / '.join(n[q['담당']]+f" {q['용돈']:,}원" for q in group))
                st.divider()
                st.write('**완료 기준**')
                st.write(first['설명'] or '등록한 가족과 완료 기준을 이야기해 주세요.')
                st.divider()
                completed = [n[q['담당']] for q in group if q['상태'] != '진행 중']
                st.write('완료한 가족: '+(' · '.join(completed) if completed else '아직 없어요'))
                st.divider()
                st.write('**📷 사진 올리고 미션 완료하기**')
                selected = large_choice('사진을 제출하거나 확인할 가족',
                    [q['담당'] for q in group], format_func=n.get, key='submitter_'+first['id'])
                q = next(item for item in group if item['담당']==selected)
                st.write('상태: '+{'진행 중':'진행 중', '지급 대기':'미션 완료 · 미션금 받을 예정', '지급 완료':'미션 완료 · 미션금 받음'}.get(q['상태'],q['상태']))
                if q.get('사진'):
                    st.image(base64.b64decode(q['사진']), caption=n[selected]+'의 완료 사진', use_container_width=True)
                if q['상태']=='진행 중':
                    photo = st.file_uploader('완료 사진 선택하기', type=['jpg','jpeg','png','webp'], key='photo_'+q['id'])
                    st.caption('선택한 가족 본인이 제출해 주세요. 현재 사용자 선택과 관계없이 이곳에서 사진을 올릴 수 있어요. 얼굴·주소는 피하고 10MB 이하 사진을 선택하세요.')
                    if st.button('📷 사진 제출하고 미션 완료!', key='finish_'+q['id'], disabled=photo is None, use_container_width=True):
                        try:
                            encoded = prepare_photo(photo.getvalue())
                            if sum(len(x.get('사진') or '') for x in d['quests'])+len(encoded)>15*1024*1024:
                                raise ValueError('사진 보관 한도에 도달했습니다.')
                            q['사진'] = encoded
                            transition_quest(q, '사진으로 미션 완료', selected)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                if actor==q['등록자'] and q['상태']=='지급 대기':
                    paid = st.checkbox('실제로 미션금을 주었습니다.', key='paid_'+q['id'])
                    if st.button('미션금 지급 완료', key='pay_'+q['id'], disabled=not paid, use_container_width=True):
                        transition_quest(q, '지급 완료', actor)
                        st.rerun()
    with tab3:
        frame = pd.DataFrame(quest_summary(d))
        own = next(row for row in quest_summary(d) if row['구성원']==n[actor])
        st.metric('내가 받을 미션금', f"{own['받을 미션금(원)']:,}원")
        st.metric('내가 받은 미션금', f"{own['받은 미션금(원)']:,}원")
        if d['quests']:
            st.subheader('가족별 미션 현황')
            rows = quest_summary(d)
            bars = []
            for row in rows:
                done = int(row['완료 미션(개)'])
                left = max(0, int(row['배정 미션(개)']) - done)
                bars.extend([{'가족':row['구성원'], '상태':'완료', '미션 수':done},
                             {'가족':row['구성원'], '상태':'남음', '미션 수':left}])
            fig = px.bar(pd.DataFrame(bars), x='미션 수', y='가족', color='상태',
                         orientation='h', barmode='stack', text='미션 수',
                         color_discrete_map={'완료':'#1751D0', '남음':'#D9DFEA'},
                         category_orders={'가족':[r['구성원'] for r in rows], '상태':['완료','남음']})
            fig.update_traces(width=0.30, texttemplate='%{text}', textposition='inside',
                              insidetextanchor='middle', textfont_size=18,
                              hovertemplate='%{y}: %{x}개<extra>%{fullData.name}</extra>')
            # Hide zero-value labels without hiding families with no assigned missions.
            for trace in fig.data:
                trace.text = [str(int(value)) if value else '' for value in trace.x]
            largest = max((int(r['배정 미션(개)']) for r in rows), default=0)
            fig.update_layout(height=max(260, 65*len(rows)+90),
                              margin=dict(l=0,r=16,t=10,b=10),
                              font=dict(size=18), plot_bgcolor='#FDFDFF', paper_bgcolor='#FDFDFF',
                              legend=dict(title=None,orientation='h',y=1.12,x=0),
                              xaxis_title=None,yaxis_title=None, bargap=0.7,
                              uniformtext_minsize=16,uniformtext_mode='hide')
            fig.update_xaxes(rangemode='tozero', range=[0,max(1,largest)*1.08],
                             dtick=max(1,math.ceil(largest/5)), showgrid=True,gridcolor='#EEF0F4',zeroline=False)
            fig.update_yaxes(showgrid=False, ticks='')
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar':False,'staticPlot':True})
            st.caption('숫자는 미션 개수예요. 파랑은 완료, 연회색은 남은 미션입니다.')
            active = [row for row in quest_summary(d) if row['배정 미션(개)']]
            if len(active)>1:
                most = max(active, key=lambda row:row['배정 미션(개)'])
                least = min(active, key=lambda row:row['배정 미션(개)'])
                if most['배정 미션(개)']-least['배정 미션(개)']>=2:
                    st.write(f"{most['구성원']}에게 미션이 더 많이 배정되어 있어요. 다음 미션은 {least['구성원']}에게 부탁해 보세요.")
        else:
            st.write('미션을 등록하면 분담과 미션금 분석이 나타나요.')


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
        st.write('요일별로 아침·점심·저녁 버튼만 눌러 주세요.')
        with st.form('availability_'+who):
            selected_slots = {}
            for day_name in DAYS:
                st.write('**'+day_name+'요일**')
                existing = [r['끼니'] for r in d['availability'] if r['구성원']==who and r['요일']==day_name]
                selected_slots[day_name] = st.pills(day_name+'요일 가능한 끼니', SLOTS,
                    selection_mode='multi', default=existing, key='avail_'+who+'_'+day_name,
                    label_visibility='collapsed') or []
                if day_name != DAYS[-1]:
                    st.divider()
            if st.form_submit_button('식사 가능 시간 저장', use_container_width=True):
                d['availability'] = [r for r in d['availability'] if r['구성원']!=who]
                for day_name, chosen in selected_slots.items():
                    for meal in chosen:
                        d['availability'].append({'구성원':who,'요일':day_name,'끼니':meal})
                st.rerun()
        result = meal_candidates(d)
        if result:
            st.subheader('함께 먹기 좋은 시간 TOP 3')
            for candidate in result[:3]:
                with st.container(border=True):
                    st.write(f"**{candidate['요일']}요일 {candidate['끼니']} · {candidate['가능 인원']}명**")
                    st.write(' · '.join(n[i] for i in candidate['참여']))
            st.write('이 중 한 끼부터 함께 먹어 보세요.')
        else:
            st.write('가족 두 명 이상이 가능한 끼니를 등록하면 함께 먹기 좋은 시간을 추천해요.')
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


HEALTH_DETAILS = {
    '흉통 또는 심한 호흡곤란': {
        '의미와 위험 신호': '새로 생긴 가슴 압박·조임이 가라앉지 않거나 팔·턱·등으로 퍼지고, 식은땀·메스꺼움·숨참이 동반되면 심장 응급질환 가능성을 배제할 수 없습니다. 통증 양상만으로 소화불량과 구별할 수 없습니다.',
        '언제 도움을 받을까요?': '지속되는 갑작스러운 흉통, 심한 호흡곤란, 위 동반 증상이 있으면 즉시 119에 연락하세요. 이미 가라앉았더라도 새롭거나 반복되는 흉통은 신속히 의료진에게 평가받으세요.',
        '지금 할 일': '활동을 멈추고 편한 자세로 쉬면서 도움을 요청하세요. 직접 운전하지 말고, 처방받지 않은 약을 임의로 복용하지 마세요.',
        '전달할 내용': '시작 시각, 지속 시간, 통증 위치·퍼지는 부위, 숨참·식은땀 여부, 심장질환 병력과 복용약을 알려 주세요.'},
    '갑작스러운 마비 또는 언어 장애': {
        '의미와 위험 신호': '웃을 때 얼굴 한쪽이 처짐, 두 팔 중 한 팔이 내려감, 말이 어눌하거나 이해가 안 되는 증상은 뇌졸중 경고 신호입니다. 갑작스러운 시력 저하·한쪽 감각 저하·균형 장애도 주의해야 합니다.',
        '언제 도움을 받을까요?': '하나라도 갑자기 생기면 즉시 119입니다. 잠깐 뒤 좋아져도 기다리지 마세요. 증상이 사라졌다고 뇌졸중 위험이 없어지는 것은 아닙니다.',
        '지금 할 일': '마지막으로 정상이었던 시각을 기록하세요. 직접 운전하지 말고, 삼킴 장애가 있을 수 있으므로 음식·물·약을 억지로 먹이지 마세요.',
        '전달할 내용': '마지막 정상 시각, 처음 발견한 증상, 항응고제 복용 여부와 기존 질환을 알려 주세요.'},
    '의식 저하 또는 실신': {
        '의미와 위험 신호': '실신은 짧게 의식을 잃는 것으로 원인이 다양합니다. 운동 중·누워 있을 때 발생했거나, 흉통·두근거림·경련·심한 부상 또는 회복 후 말·움직임 이상이 있으면 응급 평가가 필요합니다.',
        '언제 도움을 받을까요?': '지금 깨우기 어렵거나, 1분 내 깨지 않거나, 정상 호흡이 아니거나, 완전히 회복하지 못하면 즉시 119입니다. 완전히 회복해도 실제 실신을 했다면 원인 확인을 위한 진료를 받으세요.',
        '지금 할 일': '넘어져 다치지 않게 보호하고 호흡을 확인하세요. 의식이 없고 정상 호흡이 없으면 119 지시에 따라 심폐소생술을 시작하세요. 의식이 흐리면 물이나 음식을 먹이지 마세요.',
        '전달할 내용': '의식을 잃은 시간, 당시 자세·활동, 경련·흉통 유무, 회복까지 걸린 시간, 복용약을 알려 주세요.'},
    '반복되는 어지럼·두통 또는 일상생활 불편': {
        '의미와 위험 신호': '어지럼은 빙빙 도는 느낌인지, 일어날 때 아찔한지에 따라 확인할 원인이 다릅니다. 갑자기 시작된 극심한 두통, 말·시력·한쪽 팔다리 이상, 걷기 어려움이 함께 있으면 단순 피로로 넘기지 마세요.',
        '언제 도움을 받을까요?': '위험 신호가 있으면 즉시 119 또는 응급실입니다. 위험 신호 없이 반복되거나 일상 활동이 어렵다면 가까운 시일 내 내과·가정의학과 등에서 평가받으세요.',
        '지금 할 일': '넘어지지 않게 앉거나 누워 쉬고 운전·높은 곳 작업을 피하세요. 일어날 때 생기는지, 머리를 돌릴 때 생기는지 관찰하되 일부러 증상을 유발하지 마세요.',
        '전달할 내용': '발생 횟수·지속 시간·자세와의 관계, 두통 위치, 구토·귀 증상, 최근 시작하거나 바꾼 약을 기록하세요.'},
    '혈압이 반복해서 평소와 크게 다름': {
        '의미와 위험 신호': '한 번의 측정만으로 고혈압 여부를 판단할 수 없습니다. 운동·카페인·긴장, 커프 크기와 팔 위치도 수치에 영향을 줍니다. 흉통·호흡곤란·마비·언어 장애·의식 변화가 동반되면 수치보다 증상이 우선입니다.',
        '언제 도움을 받을까요?': '응급 증상이 있으면 재측정으로 지체하지 말고 119입니다. 증상이 없어도 반복해서 평소와 크게 다르거나 약 복용 후 어지럼이 생기면 처방한 의료진에게 조속히 연락하세요.',
        '지금 할 일': '조용히 5분 쉬고 등과 발을 지지한 채 팔을 심장 높이에 두고 측정하세요. 말하지 말고 1분 간격으로 2회 측정해 모두 기록하세요. 약을 임의로 추가·중단하지 마세요.',
        '전달할 내용': '측정 날짜·시각, 두 번의 혈압과 맥박, 동반 증상, 약 이름과 복용 시각, 평소 수치를 준비하세요.'},
    '수면·피로 문제가 계속됨': {
        '의미와 위험 신호': '잠을 오래 자도 개운하지 않고 심한 코골이·목격된 숨 멎음·낮 졸림이 함께 있다면 수면 중 호흡 문제 평가가 필요할 수 있습니다. 피로는 빈혈·약물·기분 문제 등 여러 원인이 있어 수면 시간만으로 원인을 알 수 없습니다.',
        '언제 도움을 받을까요?': '졸음 때문에 운전·업무가 위험하거나, 수면·피로 문제가 지속되어 생활에 지장을 주면 진료를 예약하세요. 갑작스러운 심한 숨참·흉통·의식 저하가 동반되면 즉시 119입니다.',
        '지금 할 일': '졸리면 운전하지 마세요. 1~2주간 취침·기상·야간 각성·낮잠·음주·카페인 시각을 기록하고, 처방 없이 수면제나 진정제를 추가하지 마세요.',
        '전달할 내용': '문제 시작 시점, 낮 졸림 정도, 코골이·숨 멎음 관찰 여부, 체중 변화, 복용약과 최근 생활 변화를 알려 주세요.'}
}


DAILY_DETAILS = {'눈이 피로하거나 뻑뻑해요': {'살펴볼 점': '화면을 오래 보거나 눈을 덜 깜빡이면 불편할 수 있지만 원인을 단정할 수는 없어요.', '이렇게 해보세요': '화면에서 눈을 떼고 먼 곳을 보며 자주 쉬고, 의식적으로 깜빡여 보세요. 눈을 비비지 말고 렌즈가 불편하면 빼 주세요.', '이럴 때는 상담하세요': '갑작스러운 시력 저하나 심한 눈 통증은 즉시 진료가 필요해요. 충혈·불편이 지속되거나 반복되어도 안과 상담을 받아 보세요.'}, '목·어깨가 뻐근해요': {'살펴볼 점': '같은 자세를 오래 유지한 뒤 뻐근할 수 있어요. 다친 적이 있는지도 확인해 주세요.', '이렇게 해보세요': '자세를 자주 바꾸고, 통증 없는 범위에서 부드럽게 움직여 보세요. 온찜질은 천을 사이에 두고 피부가 뜨겁지 않게 해 주세요. 목을 세게 꺾지 마세요.', '이럴 때는 상담하세요': '외상 뒤 통증, 팔의 힘 빠짐·저림 악화, 발열과 심한 목 경직은 빠른 진료가 필요해요. 계속되거나 잠·생활을 방해하면 상담해 보세요.'}, '허리가 뻐근해요': {'살펴볼 점': '오래 앉아 있거나 무리한 일을 한 뒤 불편할 수 있지만 통증만으로 원인을 알 수 없어요.', '이렇게 해보세요': '무거운 물건 들기는 피하고, 가능한 범위에서 짧게 걷거나 일상 활동을 이어가 보세요. 오래 누워만 있거나 아픈 방향으로 억지로 늘리지 마세요.', '이럴 때는 상담하세요': '새로운 소변·대변 조절 이상, 회음부 감각 저하, 양쪽 다리 힘 빠짐은 즉시 응급 진료가 필요해요. 외상·발열이 동반되거나 악화되어도 진료받으세요.'}, '가벼운 두통이 있어요': {'살펴볼 점': '수면 부족·끼니 거르기·긴장과 관련될 수 있지만, 처음 생기거나 평소와 다른 두통은 따로 살펴야 해요.', '이렇게 해보세요': '잠깐 조용한 곳에서 쉬고, 끼니와 수분 섭취가 부족하지 않았는지 확인해 보세요. 약을 자주 반복해서 먹기보다 약사·의료진에게 상담하세요.', '이럴 때는 상담하세요': '갑자기 시작된 극심한 두통, 말·시력·팔다리 이상, 발열과 목 경직이 있으면 즉시 응급 진료가 필요해요. 반복되거나 심해져도 진료받으세요.'}, '일어날 때 잠깐 어지러워요': {'살펴볼 점': '급히 일어날 때 생기는 어지럼은 혈압 변화나 약 등 여러 원인과 관련될 수 있어요.', '이렇게 해보세요': '우선 앉거나 누워 넘어지지 않게 하고, 누운 자세에서 앉기·서기를 천천히 해 보세요. 어지러운 동안 운전하지 말고 복용약은 임의로 끊지 마세요.', '이럴 때는 상담하세요': '실신, 흉통, 마비·말 이상, 걷기 어려움이 동반되면 즉시 도움을 받으세요. 반복되면 측정 기록과 약 목록을 가지고 진료받으세요.'}, '속이 더부룩하거나 가스가 차요': {'살펴볼 점': '빠른 식사나 특정 음식 뒤 불편할 수 있어요. 음식·배변·통증과의 관계를 살펴보세요.', '이렇게 해보세요': '천천히 씹어 먹고 한 번에 과식하지 말아 보세요. 가볍게 걷고, 유독 불편했던 음식이나 탄산음료를 기록해 조절해 보세요.', '이럴 때는 상담하세요': '갑작스럽고 심한 복통, 피 토함·검은 변, 배가 불러오며 대변·가스가 안 나오는 경우는 신속히 진료받으세요. 반복되거나 체중이 줄어도 상담하세요.'}, '변이 딱딱하고 보기 힘들어요': {'살펴볼 점': '배변 횟수뿐 아니라 딱딱한 변·힘주기·잔변감도 살펴보세요. 약이나 생활 변화와 관련될 수 있어요.', '이렇게 해보세요': '채소·과일·통곡물은 서서히 늘리고, 변의를 참지 말고 규칙적으로 화장실에 가 보세요. 수분 제한 지시가 없다면 평소 수분 섭취를 챙기고 가볍게 움직여 보세요.', '이럴 때는 상담하세요': '심한 복통·구토와 가스 배출 불가, 혈변은 진료가 필요해요. 갑자기 배변 습관이 바뀌거나 지속되면 약사·의료진과 상담하세요.'}, '코가 막히거나 목이 칼칼해요': {'살펴볼 점': '감기·알레르기·건조함 등 원인이 다양해요. 발열·기침·호흡 불편이 있는지도 확인해 주세요.', '이렇게 해보세요': '쉬면서 마실 수 있는 만큼 수분을 챙기고 담배 연기 등 자극을 피하세요. 코가 답답하면 약사에게 생리식염수 제품 사용법을 물어보세요.', '이럴 때는 상담하세요': '숨쉬기 어렵거나 침도 삼키기 힘들면 즉시 도움을 받으세요. 고열·탈수·악화가 있거나 면역이 약한 분은 조기에 상담하세요.'}, '잠들기 어렵거나 자주 깨요': {'살펴볼 점': '카페인·낮잠·스트레스·통증 등이 잠에 영향을 줄 수 있어요. 잠든 시간뿐 아니라 낮 생활에 미치는 영향도 중요해요.', '이렇게 해보세요': '기상 시간을 일정하게 하고, 늦은 카페인과 잠자리 직전 화면 사용을 줄여 보세요. 술로 잠을 청하거나 수면제를 임의로 추가하지 마세요.', '이럴 때는 상담하세요': '수면 문제가 계속되어 일상에 지장을 주면 상담을 권해요. 심한 코골이·목격된 숨 멎음·낮 졸림이 있다면 함께 알려 주세요. 졸릴 때는 운전하지 마세요.'}, '쉽게 피곤하고 기운이 없어요': {'살펴볼 점': '수면·식사·활동 변화뿐 아니라 약물이나 여러 질환과 관련될 수 있어요. 단순 피로라고 확정하지 않아요.', '이렇게 해보세요': '하루 활동을 작게 나누고 휴식과 규칙적인 식사를 챙겨 보세요. 무리한 운동 대신 가능한 범위에서 움직이고 피로가 시작된 시점과 수면 상태를 기록하세요.', '이럴 때는 상담하세요': '충분히 쉬어도 지속되거나 체중 감소·발열·두근거림이 동반되면 진료를 권해요. 흉통·심한 숨참·의식 저하는 즉시 119로 도움을 받으세요.'}}
HEALTH_DETAILS.update(DAILY_DETAILS)


def care_advice(symptoms):
    emergency = {'흉통 또는 심한 호흡곤란', '갑작스러운 마비 또는 언어 장애', '의식 저하 또는 실신'}
    if emergency.intersection(symptoms):
        return ('응급 여부를 먼저 확인하세요. 아래 증상별 위험 신호에 해당하거나 현재 심한 증상이 있으면 즉시 119입니다.', None)
    if symptoms:
        return (None, '선택한 불편에 맞는 생활 관리 방법을 참고해 보세요. 상담이 필요한 신호도 함께 확인해 주세요.')
    return (None, None)


def health(d):
    st.header('💚 부모님 건강')
    st.warning('생활 습관 참고용이며 진단·치료·복약 지시를 제공하지 않습니다. 개인 목표는 연령·건강 상태에 맞춰 의료진과 정하세요. 흉통, 호흡곤란, 갑작스러운 마비·언어 장애 등 급성 증상은 수치와 관계없이 119 또는 응급실 도움을 받으세요.')
    st.subheader('지금 병원 도움이 필요한가요?')
    st.write('가벼운 불편은 생활 관리 방법을 참고해 보세요. 진단이 아니며, 증상이 심해지거나 위험 신호가 있으면 진료를 우선하세요.')
    symptoms = visible_checks('요즘 어떤 점이 불편한가요? 여러 개 눌러도 돼요.',
                               list(DAILY_DETAILS), key='daily_symptoms')
    with st.expander('응급 신호 확인 · 해당될 때만 펼쳐 주세요'):
        st.write('지속되는 갑작스러운 흉통·심한 숨참, 갑작스러운 마비·말 이상, 깨우기 어려움은 즉시 119에 도움을 요청하세요.')
        urgent_symptoms = visible_checks('응급 증상',
            ['흉통 또는 심한 호흡곤란', '갑작스러운 마비 또는 언어 장애', '의식 저하 또는 실신'], key='urgent_symptoms')
    symptoms = urgent_symptoms + symptoms
    urgent, consultation = care_advice(symptoms)
    if urgent:
        st.error(urgent)
    elif consultation:
        st.write(consultation)
    else:
        st.write('증상을 선택하면 상담 안내를 드립니다. 선택하지 않았다고 건강에 이상이 없다는 뜻은 아닙니다.')
    for symptom in symptoms:
        with st.container(border=True):
            st.subheader(symptom)
            for heading, detail in HEALTH_DETAILS[symptom].items():
                st.write('**'+heading+'**')
                st.write(detail)
    st.write('아래 안내는 자가 입력에 따른 일반적인 도움말입니다. 기록만으로 질병을 판단하거나 약을 바꾸지 마세요.')
    if not require_family(d):
        return
    n = names(d)
    who = large_choice('건강을 살펴볼 가족', list(n), format_func=n.get)
    member = next(m for m in d['members'] if m['id'] == who)
    with st.form('health_add_'+who, clear_on_submit=True):
        day = st.date_input('기록 날짜', max_value=date.today())
        steps = st.number_input('하루 걸음 수(보)', 0, 100000, 0, 100)
        sleep = st.number_input('수면 시간(시간)', 0.0, 24.0, 7.0, 0.5)
        if st.form_submit_button('건강 기록 저장', use_container_width=True):
            d['health'] = [r for r in d['health'] if not (r['구성원'] == who and r['날짜'] == str(day))]
            d['health'].append({'id': uid(), '구성원': who, '날짜': str(day),
                                '걸음': steps, '수면': sleep, '수축기': None, '이완기': None, '메모': ''})
            st.rerun()
    period = large_choice('분석 기간', [7, 14, 30], format_func=lambda x: f'최근 {x}일')
    start = date.today() - timedelta(days=period-1)
    records = sorted([r for r in d['health'] if r['구성원'] == who and start <= date.fromisoformat(r['날짜']) <= date.today()], key=lambda r: r['날짜'])
    if not records:
        st.write('첫 건강 기록을 남겨 보세요.')
    else:
        frame = pd.DataFrame(records)
        mean_steps, mean_sleep = frame['걸음'].mean(), frame['수면'].mean()
        a, b, c = st.columns(3)
        a.metric('기록일 평균 걸음', f'{mean_steps:,.0f}보')
        b.metric('기록일 평균 수면', f'{mean_sleep:.1f}시간')
        c.metric('기록 일수', f'{len(records)} / {period}일')
        steps_rate = 100 * sum(r['걸음'] >= member['걸음 목표'] for r in records) / len(records)
        sleep_rate = 100 * sum(r['수면'] >= member['수면 목표'] for r in records) / len(records)
        st.write(f"개인 목표 충족일 비율: 걸음 {steps_rate:.0f}% · 수면 {sleep_rate:.0f}% (분모: 기록일 {len(records)}일)")
        if mean_steps < member['걸음 목표']:
            st.write(f"걷기 실천: 기록일 평균이 개인 목표보다 {member['걸음 목표']-mean_steps:,.0f}보 적습니다. 무리하지 않는 범위에서 짧은 산책을 가족과 나눠 시도하세요.")
        else:
            st.success('걷기: 설정한 개인 목표를 평균적으로 충족했습니다. 통증이나 피로가 있으면 운동량을 조절하고 상담하세요.')
        if mean_sleep < member['수면 목표']:
            st.write('수면 실천: 설정한 수면 목표보다 평균이 짧습니다. 일정한 취침 시간과 편안한 수면 환경을 함께 준비하세요.')
        else:
            st.write('수면: 설정한 시간 목표 이상입니다. 과도한 졸림이나 수면 불편이 있으면 별도로 상담하세요.')
        calendar = pd.DataFrame({'날짜': pd.date_range(start, date.today()).strftime('%Y-%m-%d')})
        plotted = calendar.merge(frame, on='날짜', how='left')
        plotted['걸음 목표'] = member['걸음 목표']
        plotted['수면 목표'] = member['수면 목표']
        chart(plotted, '날짜', ['걸음', '걸음 목표'], '걸음 수와 개인 목표(보)', True)
        chart(plotted, '날짜', ['수면', '수면 목표'], '수면 시간과 개인 목표(시간)', True)
        show = frame[['날짜', '걸음', '수면']].rename(columns={'걸음':'걸음(보)', '수면':'수면(시간)'})
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
    [data-testid="stPills"] button {min-height:64px; font-size:22px !important; padding:14px 18px; margin:4px; border-width:2px;}
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
    if not st.session_state.get('started', False):
        st.markdown('<div class="brand"><div style="font-size:80px" aria-hidden="true">🏡</div><h1>우리家 밸런스</h1><p>함께 나누면, 우리 가족이 더 행복해져요.</p></div>', unsafe_allow_html=True)
        st.write('집안일 퀘스트로 부담을 나누고, 함께 밥 먹고, 부모님 건강도 챙겨요.')
        if st.button('시작하기 →', use_container_width=True, type='primary'):
            st.session_state.started = True
            st.session_state.main_menu = '홈'
            st.rerun()
        return
    st.title('🏡 우리家 밸런스')
    if 'main_menu' not in st.session_state:
        st.session_state.main_menu = '홈'
    st.write('원하는 메뉴 버튼을 눌러 주세요')
    icons = ['🏠', '🎯', '🍚', '💚', '👨‍👩‍👧‍👦']
    for icon, menu in zip(icons, MENUS):
        st.button(icon+' '+menu, key='nav_'+menu, use_container_width=True,
                  type='primary' if st.session_state.main_menu == menu else 'secondary',
                  on_click=go_page, args=(menu,))
    page = st.session_state.main_menu
    st.write('현재 접속 중에만 저장됩니다. 새로고침·재접속하면 사라질 수 있습니다.')
    if st.button('로고·시작 화면으로', use_container_width=True):
        st.session_state.started = False
        st.rerun()
    d = st.session_state.data
    {'홈': home, '집안일 퀘스트': quests, '함께 식사': meals,
     '부모님 건강': health, '가족 설정': settings}[page](d)
    st.divider()


if __name__ == '__main__':
    main()
