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
        <h1 className="text-3xl font-bold mb-8">Welcome to Hub</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card className="shadow-lg rounded-lg">
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Models</CardTitle>
              <CardDescription className="text-sm">Explore our AI models</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col items-center">
              <div className="flex flex-row gap-2 mb-3 w-full">
                <Link href="/models/catalog" passHref>
                  <Button className="w-full py-2">View Catalog</Button>
                </Link>
                <Link href="/models/endpoints" passHref>
                  <Button variant="secondary" className="w-full py-2">
                    View Endpoints
                  </Button>
                </Link>
              </div>
            </CardContent>
          </Card>
          <Card className="shadow-lg rounded-lg">
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Vector Databases</CardTitle>
              <CardDescription className="text-sm">Explore our vector databases</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col items-center">
              <div className="flex flex-row gap-2 mb-3 w-full">
                <Link href="/vector-databases/catalog" passHref>
                  <Button className="w-full py-2">View Catalog</Button>
                </Link>
                <Link href="/vector-databases/endpoints" passHref>
                  <Button variant="secondary" className="w-full py-2">
                    View Endpoints
                  </Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
      <Footer />
    </div>
  );
}
