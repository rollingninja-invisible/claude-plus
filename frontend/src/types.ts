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

export type ToastOptions = {
  title: string;
  description: string;
  status?: 'info' | 'warning' | 'success' | 'error' | 'loading';
  duration?: number;
  isClosable?: boolean;
};

export interface AxiosInstanceParams {
  accessToken: string | null;
  refreshToken: string | null;
  setTokens: (accessToken: string, refreshToken: string) => void;
  clearState: () => void;
  createToast: (options: ToastOptions) => void;
}
