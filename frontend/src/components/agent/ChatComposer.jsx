// 에이전트 전용 — 입력창(.composer)
// 시안에서는 눌러도 반응 없는 장식이었는데, 실제 <input> + <button>으로 바꿔
// Enter 또는 "보내기"로 질문을 보낼 수 있게 했습니다.

import { useState } from 'react';

export default function ChatComposer({ placeholder, ariaLabel = '에이전트 질문 입력', onSend, disabled = false }) {
  const [value, setValue] = useState('');

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onSend?.(text);
    setValue('');
  }

  return (
    <div className="composer">
      <input
        className="ph2"
        type="text"
        placeholder={placeholder}
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submit();
          }
        }}
      />
      <button type="button" className="send" onClick={submit}>보내기</button>
    </div>
  );
}
