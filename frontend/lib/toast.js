import { createContext, useCallback, useContext, useRef, useState } from "react";

const ToastCtx = createContext({ success() {}, error() {}, info() {} });
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const id = useRef(0);

  const push = useCallback((kind, message, ms = 4500) => {
    const key = ++id.current;
    setItems((l) => [...l.slice(-3), { key, kind, message }]);
    setTimeout(() => setItems((l) => l.filter((t) => t.key !== key)), ms);
  }, []);

  const api = useRef({
    success: (m) => push("success", m), error: (m) => push("error", m, 7000), info: (m) => push("info", m),
  }).current;

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.key} className={`toast ${t.kind}`}>{t.message}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
