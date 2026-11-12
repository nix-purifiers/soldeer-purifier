// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;
import {Test} from "forge-std-1.11.0/src/Test.sol";
import {Counter} from "../src/Counter.sol";
contract CounterTest is Test { function testIncrement() public { Counter c = new Counter(); assertEq(c.value(), 43); c.increment(); assertEq(c.value(), 44); assertEq(c.distance(-17), 18); } }
