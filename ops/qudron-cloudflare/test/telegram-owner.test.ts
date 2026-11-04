import{describe,expect,it}from"vitest";
import{isAuthorizedTelegramOwner}from"../src/policy";
describe("Telegram owner authorization",()=>{
 const owners=new Set(["12345"]);
 it("accepts the allowlisted owner in a private one-to-one chat",()=>{
  expect(isAuthorizedTelegramOwner({chat:{id:12345,type:"private"},from:{id:12345}},owners)).toBe(true);
 });
 it("rejects a non-owner private chat",()=>{
  expect(isAuthorizedTelegramOwner({chat:{id:67890,type:"private"},from:{id:67890}},owners)).toBe(false);
 });
 it("rejects group and supergroup chats even when chat ID is allowlisted",()=>{
  expect(isAuthorizedTelegramOwner({chat:{id:12345,type:"group"},from:{id:12345}},owners)).toBe(false);
  expect(isAuthorizedTelegramOwner({chat:{id:12345,type:"supergroup"},from:{id:12345}},owners)).toBe(false);
 });
 it("rejects a forwarded or mismatched sender in the owner's private chat",()=>{
  expect(isAuthorizedTelegramOwner({chat:{id:12345,type:"private"},from:{id:99999}},owners)).toBe(false);
 });
 it("rejects missing, malformed and channel messages",()=>{
  expect(isAuthorizedTelegramOwner(null,owners)).toBe(false);
  expect(isAuthorizedTelegramOwner({chat:{id:12345,type:"private"}},owners)).toBe(false);
  expect(isAuthorizedTelegramOwner({chat:{id:12345,type:"channel"},from:{id:12345}},owners)).toBe(false);
 });
});
