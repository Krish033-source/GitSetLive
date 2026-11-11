import { useEffect } from "react";
import { useRouter } from "next/router";
import { session } from "../lib/api";
import { Spinner } from "../components/ui";

export default function Home() {
  const router = useRouter();
  useEffect(() => { router.replace(session.get() ? "/dashboard" : "/login"); }, [router]);
  return <div className="center-screen"><Spinner lg /></div>;
}
