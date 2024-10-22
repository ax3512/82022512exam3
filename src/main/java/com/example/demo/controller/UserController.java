package com.example.demo.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class UserController {
    @GetMapping("/user")
    public String getUser() {
        return "사번: 82022512";
    }

    @GetMapping("/userById")
    public String getUserById(@RequestParam(value = "id", required = true) String id) {
        return "사번: " + id;
    }
}
