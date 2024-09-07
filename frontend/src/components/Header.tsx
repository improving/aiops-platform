import Link from "next/link";
import {
  Menubar,
  MenubarMenu,
  MenubarTrigger,
  MenubarContent,
  MenubarItem,
} from "@/components/ui/menubar";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { SunIcon, MoonIcon } from "@radix-ui/react-icons";
import { useTheme } from "next-themes";

export default function Header() {
  const { setTheme } = useTheme()

  return (
    <header className="bg-background border-b">
      <div className="container mx-auto px-4 flex justify-between items-center">
        <Menubar className="flex-grow">
          <MenubarMenu>
            <MenubarTrigger className="font-bold">Model Hub</MenubarTrigger>
            <MenubarContent>
              <Link href="/" passHref>
                <MenubarItem>Home</MenubarItem>
              </Link>
            </MenubarContent>
          </MenubarMenu>
          <MenubarMenu>
            <Link href="/model-catalog" passHref>
              <MenubarTrigger>Model Catalog</MenubarTrigger>
            </Link>
          </MenubarMenu>
          <MenubarMenu>
            <Link href="/inference-endpoints" passHref>
              <MenubarTrigger>Inference Endpoints</MenubarTrigger>
            </Link>
          </MenubarMenu>
        </Menubar>
        <div className="flex items-center space-x-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon">
                <SunIcon className="h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
                <MoonIcon className="absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
                <span className="sr-only">Toggle theme</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setTheme("light")}>
                Light
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme("dark")}>
                Dark
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme("system")}>
                System
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Avatar>
            <AvatarImage src="https://github.com/infracloudio.png" />
            <AvatarFallback>CN</AvatarFallback>
          </Avatar>
        </div>
      </div>
    </header>
  );
}
