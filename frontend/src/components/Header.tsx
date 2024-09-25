import Link from "next/link";
import {
  Menubar,
  MenubarMenu,
  MenubarTrigger,
  MenubarContent,
  MenubarItem,
} from "@/components/ui/menubar";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useTheme } from "next-themes";
import { ThemeDropdown } from "./ThemeDropdown";

export default function Header() {
  const { setTheme } = useTheme();

  return (
    <header className="bg-background border-b">
      <div className="container mx-auto px-4 flex justify-between items-center mt-1 mb-1">
        <Menubar className="flex-grow">
          <MenubarMenu>
            <MenubarTrigger className="font-bold">Hub</MenubarTrigger>
            <MenubarContent>
              <Link href="/" passHref>
                <MenubarItem>Home</MenubarItem>
              </Link>
            </MenubarContent>
          </MenubarMenu>
          <MenubarMenu>
            <MenubarTrigger>Notebooks</MenubarTrigger>
            <MenubarContent>
              <Link href="/notebooks" passHref>
                <MenubarItem>Home</MenubarItem>
              </Link>
            </MenubarContent>
          </MenubarMenu>
          <MenubarMenu>
            <MenubarTrigger>Models</MenubarTrigger>
            <MenubarContent>
              <Link href="/models/catalog/" passHref>
                <MenubarItem>Catalog</MenubarItem>
              </Link>
              <Link href="/models/endpoints" passHref>
                <MenubarItem>Instances</MenubarItem>
              </Link>
            </MenubarContent>
          </MenubarMenu>
          <MenubarMenu>
            <MenubarTrigger>Vector Databases</MenubarTrigger>
            <MenubarContent>
              <Link href="/vector-databases/catalog" passHref>
                <MenubarItem>Catalog</MenubarItem>
              </Link>
              <Link href="/vector-databases/endpoints" passHref>
                <MenubarItem>Instances</MenubarItem>
              </Link>
            </MenubarContent>
          </MenubarMenu>
        </Menubar>
        <div className="flex items-center space-x-4">
          <div className="flex items-center ml-4">
            <ThemeDropdown setTheme={setTheme} />
          </div>
          <Avatar>
            <AvatarImage src="https://github.com/infracloudio.png" />
            <AvatarFallback>CN</AvatarFallback>
          </Avatar>
        </div>
      </div>
    </header>
  );
}
