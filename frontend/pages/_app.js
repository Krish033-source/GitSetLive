import Head from "next/head";
import { useRouter } from "next/router";
import { useEffect } from "react";
import "../styles/globals.css";
import Layout from "../components/Layout";
import { AuthProvider } from "../lib/auth";
import { ToastProvider } from "../lib/toast";

const PUBLIC = ["/", "/login", "/callback", "/_error", "/404"];

export default function App({ Component, pageProps }) {
  const { pathname } = useRouter();

  useEffect(() => {
    try { document.documentElement.dataset.theme = localStorage.getItem("gsl_theme") || "light"; } catch {}
  }, []);

  const page = PUBLIC.includes(pathname)
    ? <Component {...pageProps} />
    : <Layout title={Component.title}><Component {...pageProps} /></Layout>;

  return (
    <AuthProvider>
      <ToastProvider>
        <Head>
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <meta name="theme-color" content="#f4efe6" />
          <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
          <link rel="icon" href="/favicon.ico" sizes="any" />
          <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
          <link rel="manifest" href="/site.webmanifest" />
        </Head>
        {page}
      </ToastProvider>
    </AuthProvider>
  );
}
