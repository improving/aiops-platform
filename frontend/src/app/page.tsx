"use client";

import Link from "next/link";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";

export default function Home() {
  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Welcome to Model Hub</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Model Catalog</CardTitle>
              <CardDescription>Explore our AI models</CardDescription>
            </CardHeader>
            <CardContent>
              <Link href="/model-catalog" passHref>
                <Button className="w-full">View Catalog</Button>
              </Link>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Inference Endpoints</CardTitle>
              <CardDescription>Manage your deployed models</CardDescription>
            </CardHeader>
            <CardContent>
              <Link href="/inference-endpoints" passHref>
                <Button variant="secondary" className="w-full">
                  View Endpoints
                </Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </main>
      <Footer />
    </div>
  );
}
