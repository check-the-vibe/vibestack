import React from 'react';
import {render, Text} from 'ink';
import BigText from 'ink-big-text';
import Gradient from 'ink-gradient';

const WelcomeMessage = () => (
    <>
        <Gradient name="summer">
            <BigText text="VIBESTACK" font="block" align="center"/>
        </Gradient>
        <Text>Welcome to VibeStack! Run 'vibestack-menu' to access the command center.</Text>
    </>
);

render(<WelcomeMessage/>);