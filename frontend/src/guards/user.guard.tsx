import axios from 'axios';
import { flexbox, useToast } from '@chakra-ui/react';
import { GoogleLogin } from '@react-oauth/google';
import { useEffect } from 'react';
import { UserGuardProps } from '../types'; // Importing the type
import { useAuth } from '../AuthContext';

// ----------------------------------------------------------------------

const UserGuard = ({ children }: UserGuardProps) => {
  const {
    isInitialized,
    profile,
    accessToken,
    refreshToken,
    setTokens,
    clearState,
    setUserDetails,
  } = useAuth();

  const toast = useToast();

  const googleLogin = async (credential: string | undefined) => {
    if (!credential) return;

    try {
      const response = await axios.post(
        `${import.meta.env.VITE_API_URL}/auth/google`,
        { token: credential }
      );

      if (response.status !== 200) {
        throw new Error('Unauthorized User');
      }

      const data = response.data;

      localStorage.setItem('accessToken', data.access_token);
      localStorage.setItem('refreshToken', data.refresh_token);
      setTokens(data.access_token, data.refresh_token);

      // Remove sensitive data
      delete data.access_token;
      delete data.refresh_token;

      localStorage.setItem('profile', JSON.stringify(data));
      setUserDetails(data);

      toast({
        title: 'Success!',
        description: 'Successfully logged in!',
        status: 'success',
        duration: 3000,
        isClosable: true,
      });
    } catch (error) {
      if (error instanceof Error) {
        toast({
          title: 'Error logging in!',
          description:
            error.response.data.detail == 'Unauthorized Domain'
              ? 'Invalid domain email'
              : error.response.data.detail == 'Token has expired'
              ? 'Token Expired. Please login again'
              : 'An error occurred during login.',
          status: 'error',
          duration: 3000,
          isClosable: true,
        });
      } else {
        // Handle the case where the error is not an instance of Error
        toast({
          title: 'Error logging in!',
          description: 'An unknown error occurred.',
          status: 'error',
          duration: 3000,
          isClosable: true,
        });
      }
    }
  };

  // Ensure that state update logic is not in the render cycle
  useEffect(() => {
    if (!isInitialized || accessToken || refreshToken) return;
    clearState();
  }, [isInitialized, accessToken, refreshToken, clearState]);

  if (!isInitialized) {
    return <div>Loading...</div>;
  }

  if (!profile || !accessToken || !refreshToken) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100vh',
        }}
      >
        <GoogleLogin
          onSuccess={async (credentialResponse) =>
            await googleLogin(credentialResponse.credential)
          }
          onError={() => {
            toast({
              title: 'Error logging in!',
              description:
                'There was an issue when trying to log you in. Please try again.',
              status: 'error',
              duration: 3000,
              isClosable: true,
            });
          }}
        />
      </div>
    );
  }

  return children;
};

export default UserGuard;
