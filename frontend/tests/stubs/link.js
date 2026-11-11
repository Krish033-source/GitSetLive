import React from "react";
export default function Link({ href, children, ...p }) { return React.createElement("a", { href, ...p }, children); }
