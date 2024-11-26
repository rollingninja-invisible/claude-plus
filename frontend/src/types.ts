export interface FileItem {
  name: string;
  isDirectory: boolean;
  size?: string | number;
  modifiedDate?: string;
}

export interface ProfileType {
  user_id: number;
  email: string;
  name: string;
  picture: string;
}

export interface InitializeGuardProps {
  children: React.ReactNode;
}

export interface UserGuardProps {
  children: React.ReactNode;
}
