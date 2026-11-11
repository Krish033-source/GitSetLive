import { Html, Head, Main, NextScript } from "next/document";

// Applies the saved theme before first paint so there is no light/dark flash.
export default function Document() {
  return (
    <Html lang="en" data-theme="light">
      <Head />
      <body>
        <script dangerouslySetInnerHTML={{ __html: "try{var t=localStorage.getItem('gsl_theme');if(t)document.documentElement.dataset.theme=t}catch(e){}" }} />
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
